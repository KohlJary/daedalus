; From tree-sitter-c-sharp queries/tags.scm (MIT, Copyright (c) 2014-2023 Max Brunsfeld, Damien Guard,
; Amaan Qureshi and contributors). The c-sharp wheel exposes TAGS_QUERY as None.
(class_declaration name: (identifier) @name) @definition.class

; base_list entries are superclass / interface inheritance — captured as @reference.implementation
; so basemind's adapt_tslp_tags can route them to the implementations section.
(class_declaration (base_list (_) @name)) @reference.implementation

(interface_declaration name: (identifier) @name) @definition.interface

(interface_declaration (base_list (_) @name)) @reference.implementation

(method_declaration name: (identifier) @name) @definition.method

(object_creation_expression type: (identifier) @name) @reference.class

(type_parameter_constraints_clause (identifier) @name) @reference.class

(type_parameter_constraint (type type: (identifier) @name)) @reference.class

(variable_declaration type: (identifier) @name) @reference.class

(invocation_expression function: (member_access_expression name: (identifier) @name)) @reference.send

(namespace_declaration name: (identifier) @name) @definition.module

(namespace_declaration name: (identifier) @name) @module
