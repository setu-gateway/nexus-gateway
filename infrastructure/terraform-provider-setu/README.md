# terraform-provider-setu

Manage Setu Gateway organizations, projects, and API keys declaratively.

```hcl
terraform {
  required_providers {
    setu = {
      source = "setu-gateway/setu"
    }
  }
}

provider "setu" {
  endpoint = "https://gateway.your-domain.com" # or $SETU_ENDPOINT
  email    = "you@example.com"                 # or $SETU_EMAIL
  password = "..."                              # or $SETU_PASSWORD
}

resource "setu_project" "prod" {
  name            = "production"
  organization_id = "your-org-uuid"
}

resource "setu_api_key" "backend" {
  name       = "backend-service"
  project_id = setu_project.prod.id
}

output "backend_key" {
  value     = setu_api_key.backend.key
  sensitive = true
}
```

The provider authenticates the same way the dashboard login does
(`POST /auth/login`) - this is a dashboard-user credential, not a scoped API key.
The `key` attribute is only ever populated at creation time (the gateway never
returns a plaintext key again); write it to a real secret store before the next
`apply` touches this resource.

## Not yet published

This provider isn't published to the Terraform Registry - that requires a
registry account and GPG-signed releases, which is the maintainers' decision to
make, not something built here. Build and use it locally in the meantime:

```bash
go build -o terraform-provider-setu .
```

Then point Terraform at the local binary with a
[dev overrides](https://developer.hashicorp.com/terraform/cli/config/config-file#development-overrides-for-provider-developers)
block in your CLI config:

```hcl
provider_installation {
  dev_overrides {
    "setu-gateway/setu" = "/path/to/this/directory"
  }
  direct {}
}
```

## Verify

```bash
go build ./...
go vet ./...
```
