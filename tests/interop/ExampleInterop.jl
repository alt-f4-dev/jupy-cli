module ExampleInterop

const counter = Ref(0)

function increment(x::Integer)
    counter[] += 1
    return x + 1
end

include("ExampleInteropHelper.jl")

calls() = counter[]

fail() = error("interop fixture failure")

end
