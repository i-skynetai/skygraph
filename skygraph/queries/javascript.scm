; JavaScript. Same five captures as TypeScript, minus the types only TypeScript has.
(class_declaration) @container
(method_definition) @callable
(function_declaration) @callable
(variable_declarator) @bound
(field_definition) @bound
(call_expression) @call
(new_expression) @call
(import_statement) @import
; `this.svc = new FooService()` in a constructor types the field.
(assignment_expression) @binding
; `export * from './x'` and `export { a } from './x'`: a barrel forwarding names.
(export_statement) @reexport
