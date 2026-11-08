output "account_id" {
  description = "Secret AWS_ACCOUNT_ID dos quatro repos."
  value       = local.account_id
}

output "state_bucket" {
  description = "Secret TF_STATE_BUCKET dos repos de Terraform e o bucket dos backend-*.hcl."
  value       = aws_s3_bucket.state.bucket
}

output "lock_table" {
  value = aws_dynamodb_table.lock.name
}

output "ci_role_arns" {
  description = "Secret AWS_ROLE_ARN de cada repo. O da api também vai em app_ci_role_arn no envs/*.tfvars do cluster."
  value       = { for k, v in local.ci_roles : v.repo => aws_iam_role.ci[k].arn }
}

output "agent_role_arn" {
  description = "role_arn do perfil oficina-readonly no ~/.aws/config."
  value       = aws_iam_role.agent.arn
}
