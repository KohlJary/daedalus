; Daedalus addition: path calls (Type::new(), module::f(), f::<T>()), which the upstream tags query omits.
(call_expression function: (scoped_identifier name: (identifier) @name)) @reference.call
(call_expression function: (generic_function function: (scoped_identifier name: (identifier) @name))) @reference.call
(call_expression function: (generic_function function: (identifier) @name)) @reference.call
