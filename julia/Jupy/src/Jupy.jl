module Jupy

import PythonCall

export python, pyimport, load, PythonRuntime

"""A process-local Python runtime; PythonCall initializes Python only once."""
struct PythonRuntime end

const python = PythonRuntime()
const _lock = ReentrantLock()
const _modules = Dict{String, Tuple{PythonCall.Py, Union{Nothing, String}}}()

"""
    load(name; path=nothing)

Load a Python module in the persistent PythonCall interpreter. When `path`
is supplied, import a local Python source file using importlib. Repeated loads
reuse the same module, and attempts to change its source path are rejected.
"""
function load(name::AbstractString; path::Union{Nothing, AbstractString}=nothing)
    key = String(name)
    occursin(r"^[A-Za-z_][A-Za-z_0-9]*(\.[A-Za-z_][A-Za-z_0-9]*)*$", key) ||
        throw(ArgumentError("invalid Python module name: " * repr(key)))
    source = isnothing(path) ? nothing : abspath(expanduser(String(path)))
    if !isnothing(source)
        isfile(source) || throw(ArgumentError("Python source does not exist: " * source))
        source = realpath(source)
    end
    return lock(_lock) do
        if haskey(_modules, key)
            cached, previous = _modules[key]
            if !isnothing(source) && previous != source
                throw(ArgumentError("Python module " * key * " was previously loaded from " * repr(previous)))
            end
            return cached
        end
        if isnothing(source)
            mod = PythonCall.pyimport(key)
        else
            util = PythonCall.pyimport("importlib.util")
            sys = PythonCall.pyimport("sys")
            spec = util.spec_from_file_location(key, source)
            mod = util.module_from_spec(spec)
            sys.modules[key] = mod
            try
                spec.loader.exec_module(mod)
            catch
                sys.modules.pop(key)
                rethrow()
            end
        end
        _modules[key] = (mod, source)
        return mod
    end
end

"""Legacy module-loading name; retained for backwards compatibility."""
pyimport(name::AbstractString) = load(name)

"""Load a Python module through the runtime object."""
(runtime::PythonRuntime)(name::AbstractString; path=nothing) = load(name; path=path)

end
