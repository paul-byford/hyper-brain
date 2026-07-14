output "resource_name" {
  description = "The Code Interpreter extension resource name, for BRAIN_CODE_INTERPRETER."
  value       = data.external.extension.result.resource_name
}
