module ExampleInterop

const counter = Ref(0)

function increment(x::Integer)
    counter[] += 1
    return x + 1
end

calls() = counter[]

end
