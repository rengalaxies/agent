# PLAN-ONLY directory does not activate a backend until paid deployment is approved.
# Before any APPLY copy backend.s3.example to backend.tf and securely
# configure a private, encrypted, durable S3 bucket and state locking.
# A GitHub Actions ephemeral local state is never approved for apply.
