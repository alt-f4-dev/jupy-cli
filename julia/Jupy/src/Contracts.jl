# Shared Jupy Contract v1: identical schema and conservative guarantees
# as the Python implementation. TOML and expression parsing only at bind time.
module Contracts

import TOML
import PythonCall

export Contract, ContractError, ContractViolation, read_contract, bind, register,
       resolve, describe, compatibility, Registry, register_validator

struct ContractError <: Exception
    message::String
end
Base.showerror(io::IO, e::ContractError) = print(io, e.message)
struct ContractViolation <: Exception
    message::String
end
Base.showerror(io::IO, e::ContractViolation) = print(io, e.message)

struct Dimension
    factor::Int
    symbol::Union{Nothing, String}
    constant::Union{Nothing, Int}
end

function dimension(raw)
    if raw isa Integer && !(raw isa Bool) && raw >= 0
        return Dimension(1, nothing, Int(raw))
    end
    raw isa AbstractString || throw(ContractError("invalid symbolic dimension"))
    if occursin(r"^[A-Za-z_][A-Za-z_0-9]*$", raw)
        return Dimension(1, String(raw), nothing)
    end
    m = match(r"^([1-9][0-9]*)\*([A-Za-z_][A-Za-z_0-9]*)$", raw)
    isnothing(m) && throw(ContractError("invalid dimension expression: " * repr(raw)))
    factor = tryparse(Int, m.captures[1])
    isnothing(factor) && throw(ContractError("dimension coefficient overflow"))
    return Dimension(factor, m.captures[2], nothing)
end

struct Spec
    name::String
    kind::String
    dtype::Union{Nothing, String}
    shape::Vector{Dimension}
    finite::Bool
    symmetric::Bool
    validators::Vector{String}
end

const _TYPES = Set(["integer", "float", "boolean", "array"])
const _DTYPES = Set(["float32", "float64", "int32", "int64", "bool"])

function make_spec(raw; output=false)
    raw isa AbstractDict || throw(ContractError("spec must be a table"))
    issubset(Set(keys(raw)), Set(["name", "kind", "dtype", "shape", "finite", "symmetric", "validators"])) ||
        throw(ContractError("unknown spec fields"))
    name = get(raw, "name", output ? "result" : "")
    name isa AbstractString && occursin(r"^[A-Za-z_][A-Za-z_0-9]*$", name) ||
        throw(ContractError("invalid spec name"))
    kind = get(raw, "kind", nothing)
    kind in _TYPES || throw(ContractError("unsupported contract value kind"))
    dtype = get(raw, "dtype", nothing)
    if !isnothing(dtype)
        kind == "array" && dtype in _DTYPES || throw(ContractError("invalid dtype"))
    end
    dimensions = get(raw, "shape", [])
    dimensions isa Vector || throw(ContractError("shape must be a vector"))
    if kind == "array"
        haskey(raw, "shape") || throw(ContractError("array shape is required"))
    elseif haskey(raw, "shape")
        throw(ContractError("scalar cannot have array shape"))
    end
    finite = get(raw, "finite", false)
    symmetric = get(raw, "symmetric", false)
    finite isa Bool && symmetric isa Bool || throw(ContractError("predicates must be boolean"))
    finite && kind ∉ ("integer", "float", "array") &&
        throw(ContractError("finiteness requires numeric kind"))
    symmetric && !(kind == "array" && length(dimensions) == 2) &&
        throw(ContractError("symmetry requires rank-2 array"))
    validators = get(raw, "validators", String[])
    validators isa Vector && all(v -> v isa AbstractString &&
        occursin(r"^[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$", v), validators) &&
        length(unique(validators)) == length(validators) ||
        throw(ContractError("validators must be unique qualified identifiers"))
    return Spec(String(name), String(kind), isnothing(dtype) ? nothing : String(dtype),
                [dimension(d) for d in dimensions], finite, symmetric, String.(validators))
end

struct Contract
    identity::String
    version::String
    language::String
    module_name::String
    symbol::String
    inputs::Vector{Spec}
    output::Spec
    purity::String
end

function Contract(data::AbstractDict)
    issubset(Set(keys(data)), Set(["schema_version", "function", "inputs", "output", "execution"])) ||
        throw(ContractError("invalid contract root fields"))
    get(data, "schema_version", nothing) === 1 ||
        throw(ContractError("unsupported contract schema version"))
    fn = get(data, "function", nothing)
    fn isa AbstractDict || throw(ContractError("missing function table"))
    Set(keys(fn)) == Set(["id", "version", "language", "module", "symbol"]) ||
        throw(ContractError("function metadata fields invalid"))
    identity, version = fn["id"], fn["version"]
    language, mod, sym = fn["language"], fn["module"], fn["symbol"]
    identity isa AbstractString && occursin(r"^[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$", identity) ||
        throw(ContractError("invalid function identity"))
    version isa AbstractString && occursin(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", version) ||
        throw(ContractError("invalid version"))
    language in ("julia", "python") || throw(ContractError("invalid function language"))
    mod isa AbstractString && occursin(r"^[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$", mod) ||
        throw(ContractError("invalid function module"))
    sym isa AbstractString && occursin(r"^[A-Za-z_][A-Za-z_0-9]*$", sym) ||
        throw(ContractError("invalid function symbol"))
    raw_inputs = get(data, "inputs", nothing)
    raw_inputs isa Vector || throw(ContractError("inputs must be an array"))
    inputs = [make_spec(raw) for raw in raw_inputs]
    length(unique(s.name for s in inputs)) == length(inputs) ||
        throw(ContractError("duplicate input name"))
    output = make_spec(get(data, "output", nothing); output=true)
    # Output-only dimension symbols would be unconstrained and are rejected.
    bound = Set{String}()
    for arg in inputs
        arg.kind == "integer" && push!(bound, arg.name)
        for dim in arg.shape
            !isnothing(dim.symbol) && push!(bound, dim.symbol)
        end
    end
    for dim in output.shape
        !isnothing(dim.symbol) && dim.symbol ∉ bound &&
            throw(ContractError("output dimension symbol was not bound by an input"))
    end
    execution = get(data, "execution", Dict("purity" => "unknown"))
    execution isa AbstractDict && Set(keys(execution)) == Set(["purity"]) ||
        throw(ContractError("invalid execution properties"))
    purity = execution["purity"]
    purity in ("pure", "impure", "unknown") || throw(ContractError("invalid purity"))
    return Contract(String(identity), String(version), String(language),
                    String(mod), String(sym), inputs, output, String(purity))
end

read_contract(path::AbstractString) = Contract(TOML.parsefile(path))

function dimension_check!(dim::Dimension, observed::Int, bindings::Dict{String, Int}, where::String)
    if !isnothing(dim.constant)
        observed == dim.constant || throw(ContractViolation("$where: expected $(dim.constant), got $observed"))
        return
    end
    symbol = dim.symbol::String
    if !haskey(bindings, symbol)
        observed % dim.factor == 0 || throw(ContractViolation("$where: invalid symbolic dimension"))
        bindings[symbol] = div(observed, dim.factor)
    else
        expected = try
            Base.checked_mul(dim.factor, bindings[symbol])
        catch err
            err isa OverflowError || rethrow()
            throw(ContractViolation("$where: dimension coefficient overflow"))
        end
        observed == expected || throw(ContractViolation("$where: symbolic dimension mismatch"))
    end
end

function dtype_name(::Type{T}) where T
    T === Float32 && return "float32"
    T === Float64 && return "float64"
    T === Int32 && return "int32"
    T === Int64 && return "int64"
    T === Bool && return "bool"
    return "unsupported"
end

function native_scalar(value)
    # PythonCall objects remain Python objects after the call. Scalar validation
    # permits a scalar conversion only; arrays are never materialized implicitly.
    if value isa PythonCall.Py
        builtins = PythonCall.pybuiltins
        if PythonCall.pyisinstance(value, builtins.bool)
            return PythonCall.pyconvert(Bool, value)
        elseif PythonCall.pyisinstance(value, builtins.int)
            return PythonCall.pyconvert(Int, value)
        elseif PythonCall.pyisinstance(value, builtins.float)
            return PythonCall.pyconvert(Float64, value)
        end
    end
    return value
end

const _validator_lock = ReentrantLock()
const _validators = Dict{String, Any}()

function register_validator(identity::AbstractString, f)
    key = String(identity)
    occursin(r"^[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$", key) ||
        throw(ContractError("invalid validator identity"))
    lock(_validator_lock) do
        haskey(_validators, key) && throw(ContractError("validator already registered: " * key))
        _validators[key] = f
    end
    return nothing
end

function compile_validators(spec::Spec)
    return lock(_validator_lock) do
        [get(_validators, key) do
            throw(ContractError("validator not registered: " * key))
        end for key in spec.validators]
    end
end

function run_validators(validators, value, where::String)
    for validator in validators
        validator(value) === true || throw(ContractViolation("$where: custom validator rejected value"))
    end
end

function validate!(s::Spec, raw, dimensions::Dict{String,Int}, where::String, strict::Bool, validators=Any[])
    if s.kind == "array"
        raw isa AbstractArray || throw(ContractViolation("$where: expected Julia AbstractArray"))
        if !isnothing(s.dtype)
            dtype_name(eltype(raw)) == s.dtype || throw(ContractViolation("$where: wrong dtype"))
        end
        ndims(raw) == length(s.shape) || throw(ContractViolation("$where: wrong rank"))
        for (i, dim) in enumerate(s.shape)
            dimension_check!(dim, size(raw, i), dimensions, "$where axis $i")
        end
        if strict && s.symmetric
            size(raw, 1) == size(raw, 2) || throw(ContractViolation("$where: expected square matrix"))
            for j in axes(raw, 2), i in 1:j-1
                raw[i,j] == raw[j,i] || throw(ContractViolation("$where: asymmetric entries"))
            end
        end
        if strict && s.finite
            all(isfinite, raw) || throw(ContractViolation("$where: nonfinite entries"))
        end
        strict && run_validators(validators, raw, where)
        return
    end
    value = native_scalar(raw)
    if s.kind == "integer"
        value isa Integer && !(value isa Bool) || throw(ContractViolation("$where: expected integer"))
        dimensions[s.name] = Int(value)
    elseif s.kind == "boolean"
        value isa Bool || throw(ContractViolation("$where: expected boolean"))
    else
        value isa Real && !(value isa Bool) || throw(ContractViolation("$where: expected float"))
    end
    strict && s.finite && !isfinite(value) &&
        throw(ContractViolation("$where: nonfinite scalar"))
    strict && run_validators(validators, value, where)
end

function bind(f, c::Contract; mode::Symbol=:structural)
    mode in (:static, :structural, :strict, :trusted) ||
        throw(ContractError("invalid execution mode"))
    mode === :trusted && return f  # exact original callable, no wrapper
    mode === :static && throw(ContractError(
        "runtime obligations cannot be proven statically; use trusted explicitly"
    ))
    mode === :structural && any(s.finite || s.symmetric || !isempty(s.validators) for s in [c.inputs; c.output]) &&
        throw(ContractError("numerical predicates require strict validation"))
    # Contract descriptors were resolved at bind time; the hot path does not
    # inspect TOML or evaluate expressions dynamically.
    inputs = c.inputs
    output = c.output
    strict = mode === :strict
    input_validators = strict ? [compile_validators(spec) for spec in inputs] : Any[]
    output_validators = strict ? compile_validators(output) : Any[]
    function checked(args...; kwargs...)
        isempty(kwargs) || throw(ContractViolation("contracted calls are positional"))
        length(args) == length(inputs) || throw(ContractViolation("argument arity mismatch"))
        symbols = Dict{String, Int}()
        for i in eachindex(inputs)
            validate!(inputs[i], args[i], symbols, "argument $(inputs[i].name)", strict,
                      strict ? input_validators[i] : Any[])
        end
        result = f(args...)
        validate!(output, result, symbols, "result", strict, output_validators)
        return result
    end
    return checked
end

mutable struct Registry
    lock::ReentrantLock
    entries::Dict{Tuple{String, String}, Any}
    contracts::Dict{Tuple{String, String}, Contract}
    versions::Dict{String, Set{String}}
end
Registry() = Registry(ReentrantLock(), Dict{Tuple{String,String},Any}(),
                      Dict{Tuple{String,String},Contract}(), Dict{String,Set{String}}())

const registry = Registry()

function register(identity::AbstractString, f; contract::Contract, mode::Symbol=:structural, into::Registry=registry)
    identity == contract.identity || throw(ContractError("contract identity mismatch"))
    wrapped = bind(f, contract; mode)
    key = (String(identity), contract.version)
    lock(into.lock) do
        haskey(into.entries, key) && throw(ContractError("registration collision"))
        into.entries[key] = wrapped
        into.contracts[key] = contract
        push!(get!(into.versions, String(identity), Set{String}()), contract.version)
    end
    return wrapped
end

function _registry_key(identity::AbstractString, version, registry::Registry)
    if !isnothing(version)
        key = (String(identity), String(version))
        haskey(registry.entries, key) || throw(ContractError("registered contract not found"))
        return key
    end
    versions = get(registry.versions, String(identity), Set{String}())
    length(versions) == 1 || throw(ContractError("registry resolution ambiguous or missing"))
    return (String(identity), only(versions))
end

function resolve(identity::AbstractString; version=nothing, from::Registry=registry)
    lock(from.lock) do
        return from.entries[_registry_key(identity, version, from)]
    end
end
function describe(identity::AbstractString; version=nothing, from::Registry=registry)
    lock(from.lock) do
        return from.contracts[_registry_key(identity, version, from)]
    end
end

function _spec_key(s::Spec)
    return (s.kind, s.dtype,
            [(d.factor, d.symbol, d.constant) for d in s.shape], s.finite, s.symmetric, s.validators)
end
function compatibility(a::Contract, b::Contract)
    return a.identity == b.identity && a.purity == b.purity &&
           length(a.inputs) == length(b.inputs) &&
           all(_spec_key(x) == _spec_key(y) for (x,y) in zip(a.inputs,b.inputs)) &&
           _spec_key(a.output) == _spec_key(b.output)
end

end # module Contracts
