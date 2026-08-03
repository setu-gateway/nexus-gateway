package main

import (
	"context"
	"log"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"

	"github.com/setu-gateway/terraform-provider-setu/internal/provider"
)

// version is overridden at build time via -ldflags "-X main.version=..." in the
// release pipeline (see RELEASING.md); "dev" marks a locally-built binary.
var version = "dev"

func main() {
	err := providerserver.Serve(context.Background(), provider.New(version), providerserver.ServeOpts{
		Address: "registry.terraform.io/setu-gateway/setu",
	})
	if err != nil {
		log.Fatal(err.Error())
	}
}
