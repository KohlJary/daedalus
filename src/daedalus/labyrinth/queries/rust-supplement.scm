; Daedalus addition: path calls (Type::new(), module::f(), f::<T>()), which the upstream tags query omits.
(call_expression function: (scoped_identifier name: (identifier) @name)) @reference.call
(call_expression function: (generic_function function: (scoped_identifier name: (identifier) @name))) @reference.call
(call_expression function: (generic_function function: (identifier) @name)) @reference.call
; Calls inside macro invocations (assert_eq!(double(2), 4), println!, vec!): macro arguments parse as
; token trees, so an identifier followed directly by a parenthesized token tree is read as a call.
(token_tree (identifier) @name . (token_tree) @args) @reference.call
