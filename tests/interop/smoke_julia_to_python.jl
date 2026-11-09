# Opt-in end-to-end smoke test, run via jupy or juuv.
using Jupy
using PythonCall

sys = Jupy.load("sys")
again = Jupy.pyimport("sys")
@assert Jupy.load("sys") === sys
@assert sys === again

builtins = Jupy.pyimport("builtins")
@assert PythonCall.pyconvert(Int, builtins.len((1, 2, 3))) == 3

let caught = false
    try
        builtins.eval("1/0")
    catch err
        caught = err isa PythonCall.PyException
        @assert caught "Expected PythonCall.PyException, got $(typeof(err)): $(sprint(showerror, err))"
    end
    @assert caught "Python exception did not propagate with its error class"
end

local_module = Jupy.load("ExamplePythonInterop"; path=joinpath(@__DIR__, "ExamplePythonInterop.py"))
@assert PythonCall.pyconvert(Int, local_module.increment(40)) == 41
@assert PythonCall.pyconvert(Int, local_module.increment(41)) == 42
@assert Jupy.load("ExamplePythonInterop") === local_module
@assert PythonCall.pyconvert(Int, local_module.number_of_calls()) == 2
let local_caught = false
    try
        local_module.fail()
    catch err
        local_caught = err isa PythonCall.PyException
        @assert local_caught "Expected PythonCall.PyException, got $(typeof(err)): $(sprint(showerror, err))"
    end
    @assert local_caught "Local Python module exception did not propagate"
end


# Canonical source identity, alias rejection, and protection of Python sys.modules.
source_file = joinpath(@__DIR__, "ExamplePythonInterop.py")
let caught = false
    try
        Jupy.load("SecondName"; path=source_file)
    catch err
        caught = err isa ArgumentError && occursin("already loaded as", sprint(showerror, err))
    end
    @assert caught "A source file cannot be registered under two Python module names"
end
let caught = false
    try
        Jupy.load("ExamplePythonInterop"; path=joinpath(@__DIR__, "ExamplePythonInteropHelper.py"))
    catch err
        caught = err isa ArgumentError
    end
    @assert caught "An existing module name cannot change its source path"
end

# An imported module outside the Jupy registry must not be replaced.
PythonCall.pyimport("json")
let caught = false
    try
        Jupy.load("json"; path=source_file)
    catch err
        caught = err isa ArgumentError && occursin("already registered outside Jupy", sprint(showerror, err))
    end
    @assert caught "Jupy must not overwrite existing Python module identities"
end

println("Julia -> Python: canonical load, identity, state and exceptions verified")
