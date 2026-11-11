# Conformance of Julia's contract engine with the Python TOML fixtures.
using Jupy
using PythonCall
using Test

const root = normpath(joinpath(@__DIR__, "..", "contracts"))
contract(name) = Jupy.read_contract(joinpath(root, name * ".toml"))

@testset "Portable contracts and zero-wrapper specialization" begin
    c = contract("increment")
    @test c.identity == "examples.increment"
    @test c.version == "1.0.0"
    @test length(c.inputs) == 1
    @test_throws Jupy.ContractError contract("malformed")
    @test_throws Jupy.ContractError Jupy.Contract(Dict(
        "schema_version" => 1,
        "function" => Dict("id" => "examples.unbound", "version" => "1.0.0",
            "language" => "julia", "module" => "Example", "symbol" => "f"),
        "inputs" => [Dict("name" => "N", "kind" => "integer")],
        "output" => Dict("name" => "result", "kind" => "array",
                         "dtype" => "float64", "shape" => ["UNBOUND"])
    ))

    increment(x) = x + 1
    @test Jupy.bind(increment, c; mode=:trusted) === increment
    @test_throws Jupy.ContractError Jupy.bind(increment, c; mode=:static)
    bound = Jupy.bind(increment, c)
    @test bound(4) == 5
    @test_throws Jupy.ContractViolation bound(true)
    @test_throws Jupy.ContractViolation bound(4, 5)
end

@testset "Shape and dimension binding" begin
    c = contract("structural")
    f(n, matrix) = n + 1
    bound = Jupy.bind(f, c)
    @test bound(2, ones(Float64, 6, 6)) == 3
    @test_throws Jupy.ContractViolation bound(3, ones(Float64, 6, 6))
    @test_throws Jupy.ContractViolation bound(2, ones(Float32, 6, 6))
    @test_throws Jupy.ContractViolation bound(2, ones(Float64, 6, 3))
end

@testset "Numerical preconditions and postconditions" begin
    c = contract("numeric")
    @test_throws Jupy.ContractError Jupy.bind(x -> 1.0, c; mode=:structural)
    f(a) = Float64(a[1,1] + a[2,2])
    bound = Jupy.bind(f, c; mode=:strict)
    @test bound([1.0 2.0; 2.0 3.0]) == 4.0
    @test_throws Jupy.ContractViolation bound([1.0 2.0; 3.0 4.0])
    @test_throws Jupy.ContractViolation bound([Inf 0.0; 0.0 3.0])
    @test_throws Jupy.ContractViolation Jupy.bind(x -> NaN, c; mode=:strict)([1.0 0.0; 0.0 1.0])
end

@testset "Registry, collision handling, compatibility" begin
    c = contract("increment")
    r = Jupy.Registry()
    f(x) = x + 1
    bound = Jupy.register(c.identity, f; contract=c, into=r)
    @test Jupy.resolve(c.identity; from=r) === bound
    @test Jupy.describe(c.identity; from=r) === c
    @test_throws Jupy.ContractError Jupy.register(c.identity, f; contract=c, into=r)
    c2 = Jupy.Contract(Dict(
        "schema_version" => 1,
        "function" => Dict("id" => c.identity, "version" => "1.0.1",
            "language" => "julia", "module" => "ExampleInterop", "symbol" => "increment"),
        "inputs" => [Dict("name" => "value", "kind" => "integer")],
        "output" => Dict("name" => "result", "kind" => "integer"),
        "execution" => Dict("purity" => "impure")
    ))
    @test Jupy.compatibility(c, c2)
    Jupy.register(c.identity, f; contract=c2, into=r)
    @test_throws Jupy.ContractError Jupy.resolve(c.identity; from=r)
    @test Jupy.resolve(c.identity; version="1.0.1", from=r)(10) == 11
end

@testset "Contracted PythonCall function" begin
    c = contract("float")
    python_math = Jupy.load("math")
    wrapped = Jupy.bind(python_math.sqrt, c; mode=:strict)
    @test PythonCall.pyconvert(Float64, wrapped(9.0)) == 3.0
    @test_throws Jupy.ContractViolation wrapped(Inf)
end

@testset "Named domain validators with bind-time resolution" begin
    c = contract("validator")
    @test_throws Jupy.ContractError Jupy.bind(x -> x + 1, c; mode=:structural)
    @test_throws Jupy.ContractError Jupy.bind(x -> x + 1, c; mode=:strict)
    calls = Int[]
    Jupy.register_validator("examples.positive", n -> (push!(calls, n); n > 0))
    wrapped = Jupy.bind(x -> x + 1, c; mode=:strict)
    @test wrapped(2) == 3
    @test_throws Jupy.ContractViolation wrapped(-2)
    @test calls == [2, -2]
    @test_throws Jupy.ContractError Jupy.register_validator("examples.positive", n -> n > 0)
end

@testset "Contract-driven Python module binding" begin
    wrapped = Jupy.bind_contract(joinpath(root, "float.toml"); mode=:strict)
    @test PythonCall.pyconvert(Float64, wrapped(16.0)) == 4.0
    @test Jupy.resolve("examples.python_sqrt") === wrapped
end

@testset "Native Julia method inventory" begin
    Base.include(Main, joinpath(@__DIR__, "ExampleInterop.jl"))
    inventory = Jupy.inspect_julia(Main.ExampleInterop)
    @test occursin("ExampleInterop", inventory)
    @test occursin("increment", inventory)
    @test occursin("integer", inventory)
    @test Jupy.inspect_julia(Main.ExampleInterop) === inventory
end

println("Julia contracts: conformance, binding, native method discovery and Python calls passed")
