; TypeScript (and TSX, which shares this file). Five captures, read by one interpreter:
;   @container  a named thing with members — every one becomes a Class
;   @callable   a function or method
;   @bound      a name bound to a function value: `const handler = () => {}`
;   @call       a call site; the callee text is read by the interpreter
;   @import     an import; the module text is read by the interpreter
(class_declaration) @container
(abstract_class_declaration) @container
(interface_declaration) @container
(enum_declaration) @container
(method_definition) @callable
(function_declaration) @callable
(function_signature) @callable
(method_signature) @callable
(variable_declarator) @bound
(public_field_definition) @bound
(call_expression) @call
(new_expression) @call
(import_statement) @import
; A name bound to a type: fields and parameters. `variable_declarator` is
; already @bound; the interpreter treats one whose value is not a function as a binding.
(public_field_definition) @binding
(required_parameter) @binding
(optional_parameter) @binding
; `this.svc = new FooService()` in a constructor types the field.
(assignment_expression) @binding
; `export * from './x'` and `export { a } from './x'`: a barrel forwarding names.
(export_statement) @reexport
