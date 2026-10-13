# Intentionally unconfigured remote state.
# The GitHub plan-only workflow uses terraform init -backend=false.
# Before ANY apply initialize this S3 backend with an encrypted,
# private Cloud.ru OBS bucket, state locking, and restricted credentials.
# Do not inject bucket secrets into git or terraform source files.
terraform {
  backend "s3" {}
}
