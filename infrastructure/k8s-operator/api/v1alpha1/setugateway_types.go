// Package v1alpha1 contains the SetuGateway custom resource: a declarative desired
// state for a running gateway (image/version, replica count, and the Secret holding
// its DATABASE_URL/REDIS_URL/JWT_SECRET/provider keys), reconciled by
// internal/controller/setugateway_controller.go into a real Deployment + Service.
// +kubebuilder:object:generate=true
// +groupName=setu.gateway.io
package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// GroupVersion is the API group and version used for SetuGateway.
var GroupVersion = schema.GroupVersion{Group: "setu.gateway.io", Version: "v1alpha1"}

// SchemeBuilder is used to add go types to the GroupVersionKind scheme.
var SchemeBuilder = runtime.NewSchemeBuilder(addKnownTypes)

// AddToScheme adds SetuGateway types to the given scheme.
var AddToScheme = SchemeBuilder.AddToScheme

func addKnownTypes(scheme *runtime.Scheme) error {
	scheme.AddKnownTypes(GroupVersion,
		&SetuGateway{},
		&SetuGatewayList{},
	)
	metav1.AddToGroupVersion(scheme, GroupVersion)
	return nil
}

// SetuGatewaySpec defines the desired state of a SetuGateway deployment.
type SetuGatewaySpec struct {
	// Image is the container image repository, e.g. "ghcr.io/setu-gateway/gateway".
	// +kubebuilder:validation:Required
	Image string `json:"image"`

	// Version is the image tag to run. Changing this triggers a rolling upgrade -
	// this is the operator's "auto upgrades" capability: edit one field, the
	// running Deployment converges to it without a separate kubectl/helm step.
	// +kubebuilder:validation:Required
	Version string `json:"version"`

	// Replicas is the desired pod count.
	// +kubebuilder:default=2
	// +kubebuilder:validation:Minimum=1
	Replicas int32 `json:"replicas,omitempty"`

	// SecretName is the Secret holding DATABASE_URL/REDIS_URL/JWT_SECRET/provider
	// keys, in the same namespace as this SetuGateway. When its contents change,
	// the operator rolls the Deployment's pods automatically (see
	// internal/controller's secret-hash annotation) - this is the operator's
	// "secret rotation" capability: update the Secret, the running pods pick it up
	// without a manual restart.
	// +kubebuilder:validation:Required
	SecretName string `json:"secretName"`

	// Port is the container port the gateway listens on.
	// +kubebuilder:default=8000
	Port int32 `json:"port,omitempty"`
}

// SetuGatewayPhase summarizes reconciliation status for `kubectl get`.
type SetuGatewayPhase string

const (
	PhasePending   SetuGatewayPhase = "Pending"
	PhaseReady     SetuGatewayPhase = "Ready"
	PhaseDegraded  SetuGatewayPhase = "Degraded"
)

// SetuGatewayStatus reflects the operator's most recent observation of the
// Deployment it manages - this is the "health recovery" visibility capability:
// a degraded Deployment shows up here, not just in a separate `kubectl get pods`.
type SetuGatewayStatus struct {
	Phase               SetuGatewayPhase `json:"phase,omitempty"`
	ReadyReplicas       int32            `json:"readyReplicas,omitempty"`
	ObservedSecretHash  string           `json:"observedSecretHash,omitempty"`
	ObservedGeneration  int64            `json:"observedGeneration,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`
// +kubebuilder:printcolumn:name="Ready",type=integer,JSONPath=`.status.readyReplicas`
// +kubebuilder:printcolumn:name="Version",type=string,JSONPath=`.spec.version`

// SetuGateway is the Schema for the setugateways API.
type SetuGateway struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   SetuGatewaySpec   `json:"spec,omitempty"`
	Status SetuGatewayStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// SetuGatewayList contains a list of SetuGateway.
type SetuGatewayList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []SetuGateway `json:"items"`
}
