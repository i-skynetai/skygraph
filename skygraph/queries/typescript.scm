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
