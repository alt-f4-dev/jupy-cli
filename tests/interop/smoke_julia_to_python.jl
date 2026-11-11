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
        Jupy.load("json"; path=joinpath(@__DIR__, "ExamplePythonInteropHelper.py"))
    catch err
        caught = err isa ArgumentError && occursin("already registered outside Jupy", sprint(showerror, err))
    end
    @assert caught "Jupy must not overwrite existing Python module identities"
end

# Ordinary loading prepares an annotation inventory once, while preserving
# the underlying PythonCall.Py identity and native method semantics.
inventory = Jupy.inspect_module("ExamplePythonInterop")
@assert inventory !== nothing
@assert inventory["source"] == "runtime_python_inspection" inventory
functions = Dict(f["name"] => f for f in inventory["functions"])
@assert haskey(functions, "annotated_increment")
@assert functions["annotated_increment"]["arguments"] == ["integer"]
@assert functions["annotated_increment"]["returns"] == "integer"
@assert haskey(functions, "unknown_interface")
@assert functions["unknown_interface"]["arguments"] == ["any"]
@assert PythonCall.pyconvert(Int, local_module.annotated_increment(4)) == 5

@assert PythonCall.pyconvert(Int, local_module.guarded_increment(4)) == 5
let caught = false
    try
        local_module.guarded_increment("wrong")
    catch err
        caught = err isa PythonCall.PyException
    end
    @assert caught "Developer-instrumented function must reject incompatible input"
end

view = Jupy.checked_module("ExamplePythonInterop")
@assert PythonCall.pyconvert(Int, view.annotated_increment(5)) == 6
let caught = false
    try
        view.annotated_increment("bad")
    catch err
        caught = err isa PythonCall.PyException
    end
    @assert caught "Checked annotation view did not reject incompatible argument"
end
@assert Jupy.load("ExamplePythonInterop") === local_module

println("Julia -> Python: native identity, discovery, author enforcement, and checked views verified")
