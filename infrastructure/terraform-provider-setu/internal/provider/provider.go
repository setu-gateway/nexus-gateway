package provider

import (
	"context"
	"os"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var _ provider.Provider = &setuProvider{}

type setuProvider struct {
	version string
}

type setuProviderModel struct {
	Endpoint types.String `tfsdk:"endpoint"`
	Email    types.String `tfsdk:"email"`
	Password types.String `tfsdk:"password"`
}

func New(version string) func() provider.Provider {
	return func() provider.Provider {
		return &setuProvider{version: version}
	}
}

func (p *setuProvider) Metadata(_ context.Context, _ provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "setu"
	resp.Version = p.version
}

func (p *setuProvider) Schema(_ context.Context, _ provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "Manage Setu Gateway organizations, projects, and API keys declaratively. " +
			"Authenticates the same way the dashboard login does (POST /auth/login) - " +
			"this is a dashboard-user credential, not a scoped API key.",
		Attributes: map[string]schema.Attribute{
			"endpoint": schema.StringAttribute{
				Optional:    true,
				Description: "Gateway base URL. Defaults to $SETU_ENDPOINT, then http://localhost:8000.",
			},
			"email": schema.StringAttribute{
				Optional:    true,
				Description: "Dashboard user email. Defaults to $SETU_EMAIL.",
			},
			"password": schema.StringAttribute{
				Optional:    true,
				Sensitive:   true,
				Description: "Dashboard user password. Defaults to $SETU_PASSWORD.",
			},
		},
	}
}

func (p *setuProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var config setuProviderModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &config)...)
	if resp.Diagnostics.HasError() {
		return
	}

	endpoint := firstNonEmpty(config.Endpoint.ValueString(), os.Getenv("SETU_ENDPOINT"), "http://localhost:8000")
	email := firstNonEmpty(config.Email.ValueString(), os.Getenv("SETU_EMAIL"))
	password := firstNonEmpty(config.Password.ValueString(), os.Getenv("SETU_PASSWORD"))

	if email == "" || password == "" {
		resp.Diagnostics.AddError(
			"Missing credentials",
			"Set the provider's email/password attributes, or SETU_EMAIL/SETU_PASSWORD environment variables.",
		)
		return
	}

	c := newClient(endpoint, email, password)
	if err := c.login(ctx); err != nil {
		resp.Diagnostics.AddError("Unable to authenticate with Setu Gateway", err.Error())
		return
	}

	resp.ResourceData = c
	resp.DataSourceData = c
}

func (p *setuProvider) Resources(_ context.Context) []func() resource.Resource {
	return []func() resource.Resource{
		newProjectResource,
		newAPIKeyResource,
	}
}

func (p *setuProvider) DataSources(_ context.Context) []func() datasource.DataSource {
	return nil
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}
