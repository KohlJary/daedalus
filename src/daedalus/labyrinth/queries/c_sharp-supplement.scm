; Daedalus addition: plain calls (Helper(x)); the upstream tags query captures only member sends.
(invocation_expression function: (identifier) @name) @reference.call
; Generic invocations name a type: bUnit's RenderComponent<Counter>(), DI's AddScoped<IFoo, Foo>()
(invocation_expression function: (generic_name (type_argument_list (identifier) @name))) @reference.class
(invocation_expression function: (member_access_expression name: (generic_name (type_argument_list (identifier) @name)))) @reference.class
; Records, structs and constructors are code units too (the upstream tags query leaves them out)
(record_declaration name: (identifier) @name) @definition.class
(struct_declaration name: (identifier) @name) @definition.class
(constructor_declaration name: (identifier) @name) @definition.method
