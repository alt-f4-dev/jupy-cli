module Jupy

import PythonCall

include("Contracts.jl")
using .Contracts: Contract, ContractError, ContractViolation, read_contract, bind,
                  register, resolve, describe, compatibility, Registry

export Contract, ContractError, ContractViolation, read_contract, bind_contract, bind,
       register, resolve, describe, compatibility, Registry

export python, pyimport, load, PythonRuntime

"""Use the process-local Python interpreter initialized by PythonCall."""
struct PythonRuntime end

const python = PythonRuntime()
const _lock = ReentrantLock()
const _modules = Dict{String, Tuple{PythonCall.Py, Union{Nothing, String}}}()
const _sources = Dict{String, String}()

"""
    load(name; path=nothing)

Load an installed Python module, or a single local `.py` module when `path`
is supplied. Each module name and canonical source path has one identity for
the lifetime of the process. Hot reload and changing the source are unsupported.

An untracked module already present in Python's `sys.modules` is never
silently overwritten when loading a file. Import failures do not register
Jupy cache entries and remove the partially created module from sys.modules.
"""
function load(name::AbstractString; path::Union{Nothing, AbstractString}=nothing)
    key = String(name)
    occursin(r"^[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$", key) ||
        throw(ArgumentError("invalid Python module name: " * repr(key)))
    source = isnothing(path) ? nothing : abspath(expanduser(String(path)))
    if !isnothing(source)
        occursin('.', key) && throw(ArgumentError("local Python sources require a simple module name"))
        isfile(source) || throw(ArgumentError("Python source does not exist: " * source))
        source = realpath(source)
    end

    return lock(_lock) do
        if haskey(_modules, key)
            cached, previous = _modules[key]
            if !isnothing(source) && source != previous
                throw(ArgumentError("Python module " * key * " already loaded from " * repr(previous)))
            end
            return cached
        end
        if !isnothing(source)
            previous_name = get(_sources, source, nothing)
            if !isnothing(previous_name) && previous_name != key
                throw(ArgumentError("Python source " * source * " already loaded as " * previous_name))
            end
        end

        if isnothing(source)
            mod = PythonCall.pyimport(key)
        else
            util = PythonCall.pyimport("importlib.util")
            sys = PythonCall.pyimport("sys")
            occupied = PythonCall.pyconvert(Bool, sys.modules.__contains__(key))
            occupied && throw(ArgumentError(
                "Python module " * key * " is already registered outside Jupy; refusing to overwrite sys.modules"
            ))
            spec = util.spec_from_file_location(key, source)
            mod = util.module_from_spec(spec)
            sys.modules[key] = mod
            try
                spec.loader.exec_module(mod)
            catch
                sys.modules.pop(key, nothing)
                rethrow()
            end
        end
        _modules[key] = (mod, source)
        if !isnothing(source)
            _sources[source] = key
        end
        return mod
    end
end

"""
    bind_contract(contract; path=nothing, mode=:structural)

Resolve the Python callable declared by a contract once using the Phase 1
loader, specialize it, and register the callable under its contract identity.
"""
function bind_contract(c::Contract; path=nothing, mode::Symbol=:structural)
    c.language == "python" || throw(ContractError("Julia-hosted contracts must target Python"))
    module_handle = load(c.module_name; path=path)
    target = getproperty(module_handle, Symbol(c.symbol))
    return register(c.identity, target; contract=c, mode=mode)
end
bind_contract(path::AbstractString; kwargs...) =
    bind_contract(read_contract(path); kwargs...)


"""Compatibility alias for the canonical `load` interface."""
pyimport(name::AbstractString) = load(name)

"""Load a Python module through the runtime handle."""
(runtime::PythonRuntime)(name::AbstractString; path=nothing) = load(name; path=path)

end
