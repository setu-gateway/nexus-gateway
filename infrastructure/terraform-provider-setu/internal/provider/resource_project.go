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

var _ resource.Resource = &projectResourceType{}
var _ resource.ResourceWithConfigure = &projectResourceType{}
var _ resource.ResourceWithImportState = &projectResourceType{}

func newProjectResource() resource.Resource {
	return &projectResourceType{}
}

type projectResourceType struct {
	client *client
}

type projectModel struct {
	ID             types.String `tfsdk:"id"`
	Name           types.String `tfsdk:"name"`
	OrganizationID types.String `tfsdk:"organization_id"`
	Description    types.String `tfsdk:"description"`
}

func (r *projectResourceType) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_project"
}

func (r *projectResourceType) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = schema.Schema{
		Description: "A Setu Gateway project (apps/gateway/api/projects.py) - the unit API keys are issued under.",
		Attributes: map[string]schema.Attribute{
			"id": schema.StringAttribute{
				Computed:      true,
				Description:   "Project UUID, assigned by the gateway.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.UseStateForUnknown()},
			},
			"name": schema.StringAttribute{
				Required:    true,
				Description: "Project name.",
			},
			"organization_id": schema.StringAttribute{
				Required:      true,
				Description:   "Owning organization UUID. Changing this forces recreation.",
				PlanModifiers: []planmodifier.String{stringplanmodifier.RequiresReplace()},
			},
			"description": schema.StringAttribute{
				Optional:    true,
				Description: "Optional project description.",
			},
		},
	}
}

func (r *projectResourceType) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
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

func (r *projectResourceType) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan projectModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	var description *string
	if !plan.Description.IsNull() {
		v := plan.Description.ValueString()
		description = &v
	}

	created, err := r.client.createProject(ctx, plan.Name.ValueString(), plan.OrganizationID.ValueString(), description)
	if err != nil {
		resp.Diagnostics.AddError("Error creating project", err.Error())
		return
	}

	plan.ID = types.StringValue(created.ID)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *projectResourceType) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	var state projectModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	found, err := r.client.getProject(ctx, state.ID.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Error reading project", err.Error())
		return
	}

	state.Name = types.StringValue(found.Name)
	state.OrganizationID = types.StringValue(found.OrganizationID)
	if found.Description != nil {
		state.Description = types.StringValue(*found.Description)
	} else {
		state.Description = types.StringNull()
	}
	resp.Diagnostics.Append(resp.State.Set(ctx, &state)...)
}

func (r *projectResourceType) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	var plan projectModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	name := plan.Name.ValueString()
	var description *string
	if !plan.Description.IsNull() {
		v := plan.Description.ValueString()
		description = &v
	}

	updated, err := r.client.updateProject(ctx, plan.ID.ValueString(), &name, description)
	if err != nil {
		resp.Diagnostics.AddError("Error updating project", err.Error())
		return
	}

	plan.Name = types.StringValue(updated.Name)
	resp.Diagnostics.Append(resp.State.Set(ctx, &plan)...)
}

func (r *projectResourceType) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	var state projectModel
	resp.Diagnostics.Append(req.State.Get(ctx, &state)...)
	if resp.Diagnostics.HasError() {
		return
	}

	if err := r.client.deleteProject(ctx, state.ID.ValueString()); err != nil {
		resp.Diagnostics.AddError("Error deleting project", err.Error())
	}
}

func (r *projectResourceType) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)
}
