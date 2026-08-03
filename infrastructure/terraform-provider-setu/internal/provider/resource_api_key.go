package provider

import (
	"context"
	"fmt"

	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var _ resource.Resource = &apiKeyResourceType{}
var _ resource.ResourceWithConfigure = &apiKeyResourceType{}
var _ resource.ResourceWithImportState = &apiKeyResourceType{}

func newAPIKeyResource() resource.Resource {
	return &apiKeyResourceType{}
}

type apiKeyResourceType struct {
	client *client
}

type apiKeyModel struct {
	ID        types.String `tfsdk:"id"`
	Name      types.String `tfsdk:"name"`
	ProjectID types.String `tfsdk:"project_id"`
	Key       types.String `tfsdk:"key"`
	MaskedKey types.String `tfsdk:"masked_key"`
}

func (r *apiKeyResourceType) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_api_key"
}

func (r *apiKeyResourceType) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A scoped Setu Gateway API key (apps/gateway/api/keys.py). Keys have no update endpoint - " +
			"changing name or project_id destroys and recreates the key, exactly like rotating it by hand.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:      true,
				Description:   "Key UUID, assigned by the gateway.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"name": schema.StringAttribute{
				Required:      true,
				Description:   "Human-readable key label.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"project_id": schema.StringAttribute{
				Required:      true,
				Description:   "Owning project UUID.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"key": schema.StringAttribute{
				Computed:    true,
				Sensitive:   true,
				Description: "Plaintext key - the gateway returns this exactly once, at creation. Store it (e.g. in a secret manager) before the next apply; it cannot be recovered afterward.",
				PlanModifiers: []planmodifier.String{
					stringplanmodifier.UseStateForUnknown(),
				},
			},
			"masked_key": schema.StringAttribute{
				Computed:      true,
				Description:   "Masked key, safe to display (e.g. \"sk_setu_...ab12\").",
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
		},
	}
}

func (r *apiKeyResourceType) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	if req.ProviderData == nil {
		return
	}
	c, ok := req.ProviderData.(*client)
	if !ok {
		resp.Diagnostics.AddError("Unexpected provider data type", fmt.Sprintf("expected *client, got %T", req.ProviderData))
		return
	}
	r.client = c
}

func (r *apiKeyResourceType) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan apiKeyModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	created, err := r.client.createAPIKey(ctx, plan.ProjectID.ValueString(), plan.Name.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Error creating API key", err.Error())
		return
	}

	plan.ID = types.StringValue(created.ID)
	plan.Key = types.StringValue(created.Key)
	plan.MaskedKey = types.StringValue(created.MaskedKey)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *apiKeyResourceType) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state apiKeyModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	found, err := r.client.getAPIKey(ctx, state.ID.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Error reading API key", err.Error())
		return
	}

	// The plaintext key is only ever returned once, at creation - GET /keys/{id}
	// intentionally never includes it again, so `state.Key` is left untouched here
	// rather than nulled out, which would otherwise show as a spurious diff on
	// every plan.
	state.Name = types.StringValue(found.Name)
	state.ProjectID = types.StringValue(found.ProjectID)
	state.MaskedKey = types.StringValue(found.MaskedKey)
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

func (r *apiKeyResourceType) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	// Unreachable in practice: every attribute that could change triggers
	// RequiresReplace, so Terraform never calls Update for this resource. Still
	// required to satisfy resource.Resource.
	var plan apiKeyModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *apiKeyResourceType) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state apiKeyModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	if err := r.client.deleteAPIKey(ctx, state.ID.ValueString()); err != nil {
		resp.Diagnostics.AddError("Error deleting API key", err.Error())
	}
}

func (r *apiKeyResourceType) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
