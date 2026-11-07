module Jupy

import PythonCall

export python, pyimport, PythonRuntime

"""A process-local Python runtime; PythonCall initializes Python only once."""
struct PythonRuntime end

const python = PythonRuntime()
const _modules = Dict{String, PythonCall.Py}()

"""Import and cache a Python module in the current Julia process."""
function pyimport(name::AbstractString)
    key = String(name)
    isempty(key) && throw(ArgumentError("Python module name cannot be empty"))
    return get!(_modules, key) do
        PythonCall.pyimport(key)
    end
end

"""Allow a runtime object to import a Python module without creating another interpreter."""
(runtime::PythonRuntime)(name::AbstractString) = pyimport(name)

end
