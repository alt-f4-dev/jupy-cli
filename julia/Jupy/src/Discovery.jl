# Native, read-only Julia reflection for cross-language interface discovery.
# The generated inventory describes declarations; it does not assert that
# implementations obey postconditions or that values satisfy physical laws.
module Discovery

import TOML

export inspect_julia, python_inventory

const _lock = ReentrantLock()
const _native = IdDict{Module, String}()
const _python = Dict{String, Dict{String, Any}}()

function _kind(T)
    T isa Type || return "any"
    T <: Bool && return "boolean"
    T <: Integer && return "integer"
    T <: AbstractFloat && return "float"
    T <: AbstractArray && return "array"
    return "any"
end

"""
    inspect_julia(module; refresh=false)

Build a deterministic, descriptive TOML inventory of locally
defined Julia methods without invoking the methods or evaluating source.
Reflection is cached by module identity. Julia dispatch itself enforces
declared method argument types; output properties remain unknown.
"""
function inspect_julia(mod::Module; refresh::Bool=false)
    return lock(_lock) do
        !refresh && haskey(_native, mod) && return _native[mod]
        functions = Dict{String, Any}[]
        for name in sort!(collect(names(mod; all=true, imported=false)); by=string)
            isdefined(mod, name) || continue
            value = getfield(mod, name)
            value isa Function || continue
            signatures = Dict{String, Any}[]
            for meth in methods(value)
                meth.module === mod || continue
                types = Base.unwrap_unionall(meth.sig).parameters
                args = [string(_kind(T)) for T in collect(types)[2:end]]
                push!(signatures, Dict(
                    "signature" => string(meth.sig),
                    "arguments" => args,
                    "returns" => "any",
                    "provenance" => "julia_method_dispatch",
                ))
            end
            isempty(signatures) && continue
            sort!(signatures; by=x->x["signature"])
            push!(functions, Dict("name" => string(name), "methods" => signatures))
        end
        io = IOBuffer()
        TOML.print(io, Dict(
            "module" => string(nameof(mod)),
            "language" => "julia",
            "source" => "runtime_method_reflection",
            "functions" => functions,
        ))
        manifest = String(take!(io))
        _native[mod] = manifest
        return manifest
    end
end

"""
    python_inventory(key, module)

Inspect locally declared Python functions through Python's installed Jupy
inspector. Missing optional tooling does not change the native module result:
the inventory records unavailability rather than assuming guarantees.
"""
function python_inventory(key::AbstractString, module_handle)
    return lock(_lock) do
        haskey(_python, String(key)) && return _python[String(key)]
        metadata = Dict{String, Any}(
            "module" => String(key),
            "language" => "python",
            "source" => "unavailable",
            "functions" => Any[],
        )
        try
            inspector = parentmodule(@__MODULE__).PythonCall.pyimport("jupy.discovery")
            wire = parentmodule(@__MODULE__).PythonCall.pyconvert(
                String, inspector.wire_python(module_handle)
            )
            functions = Any[]
            for line in split(wire, '\n'; keepempty=false)
                fields = split(line, '\t'; keepempty=true)
                length(fields) == 3 || continue
                push!(functions, Dict(
                    "name" => fields[1],
                    "arguments" => isempty(fields[2]) ? String[] : split(fields[2], ","),
                    "returns" => fields[3],
                    "provenance" => "python_annotations",
                ))
            end
            metadata["functions"] = functions
            metadata["source"] = "runtime_python_inspection"
        catch err
            # Keep discovery advisory; native module loading must still work.
            metadata["reason"] = string(typeof(err))
        end
        _python[String(key)] = metadata
        return metadata
    end
end

function python_manifest(key::AbstractString)
    return lock(_lock) do
        get(_python, String(key), nothing)
    end
end

end # module Discovery
