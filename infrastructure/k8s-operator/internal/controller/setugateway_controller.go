package controller

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"

	setuv1alpha1 "github.com/setu-gateway/setu-gateway-operator/api/v1alpha1"
)

const secretHashAnnotation = "setu.gateway.io/secret-hash"

// SetuGatewayReconciler reconciles a SetuGateway object into a real Deployment +
// Service, and reflects that Deployment's health back onto the SetuGateway's
// status - the three operator capabilities from Epic 7.8: auto upgrades (edit
// spec.version, the Deployment's image converges), secret rotation (edit the
// referenced Secret, pods roll automatically via the hash annotation below), and
// health recovery visibility (status.phase reflects the Deployment's real state).
// Scaling is edit spec.replicas, the same convergence mechanism as version.
type SetuGatewayReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=setu.gateway.io,resources=setugateways,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=setu.gateway.io,resources=setugateways/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=services;secrets,verbs=get;list;watch;create;update;patch;delete

func (r *SetuGatewayReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := ctrl.LoggerFrom(ctx)

	var gw setuv1alpha1.SetuGateway
	if err := r.Get(ctx, req.NamespacedName, &gw); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	var secret corev1.Secret
	if err := r.Get(ctx, types.NamespacedName{Name: gw.Spec.SecretName, Namespace: gw.Namespace}, &secret); err != nil {
		return ctrl.Result{}, fmt.Errorf("fetching secret %q: %w", gw.Spec.SecretName, err)
	}
	secretHash := hashSecretData(secret.Data)

	deployment := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: gw.Name, Namespace: gw.Namespace}}
	result, err := controllerutil.CreateOrUpdate(ctx, r.Client, deployment, func() error {
		replicas := gw.Spec.Replicas
		if replicas == 0 {
			replicas = 2
		}
		port := gw.Spec.Port
		if port == 0 {
			port = 8000
		}

		deployment.Spec.Replicas = &replicas
		deployment.Spec.Selector = &metav1.LabelSelector{MatchLabels: map[string]string{"setu.gateway.io/name": gw.Name}}
		if deployment.Spec.Template.ObjectMeta.Labels == nil {
			deployment.Spec.Template.ObjectMeta.Labels = map[string]string{}
		}
		deployment.Spec.Template.ObjectMeta.Labels["setu.gateway.io/name"] = gw.Name
		if deployment.Spec.Template.ObjectMeta.Annotations == nil {
			deployment.Spec.Template.ObjectMeta.Annotations = map[string]string{}
		}
		// Changing a pod template annotation is what actually triggers a rolling
		// restart - this is the real mechanism ("secret rotation"), not a comment.
		deployment.Spec.Template.ObjectMeta.Annotations[secretHashAnnotation] = secretHash

		container := corev1.Container{
			Name:  "gateway",
			Image: fmt.Sprintf("%s:%s", gw.Spec.Image, gw.Spec.Version),
			// Kubernetes defaults an unset pull policy to Always for a "latest" (or
			// omitted) tag - that ignores an image already present on the node
			// (e.g. via `kind load docker-image` for local dev/CI) and tries a
			// real registry pull instead, which is the actual cause of an
			// ImagePullBackOff on an image that's genuinely already there.
			ImagePullPolicy: corev1.PullIfNotPresent,
			Ports:           []corev1.ContainerPort{{ContainerPort: port}},
			EnvFrom: []corev1.EnvFromSource{
				{SecretRef: &corev1.SecretEnvSource{LocalObjectReference: corev1.LocalObjectReference{Name: gw.Spec.SecretName}}},
			},
		}
		if len(deployment.Spec.Template.Spec.Containers) == 0 {
			deployment.Spec.Template.Spec.Containers = []corev1.Container{container}
		} else {
			deployment.Spec.Template.Spec.Containers[0] = container
		}

		return controllerutil.SetControllerReference(&gw, deployment, r.Scheme)
	})
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("reconciling deployment: %w", err)
	}
	if result != controllerutil.OperationResultNone {
		logger.Info("reconciled deployment", "name", gw.Name, "result", result)
	}

	if err := r.reconcileService(ctx, &gw); err != nil {
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, r.updateStatus(ctx, &gw, deployment, secretHash)
}

func (r *SetuGatewayReconciler) reconcileService(ctx context.Context, gw *setuv1alpha1.SetuGateway) error {
	port := gw.Spec.Port
	if port == 0 {
		port = 8000
	}
	svc := &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: gw.Name, Namespace: gw.Namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, svc, func() error {
		svc.Spec.Selector = map[string]string{"setu.gateway.io/name": gw.Name}
		svc.Spec.Ports = []corev1.ServicePort{{Port: port, TargetPort: intstr.FromInt32(port)}}
		return controllerutil.SetControllerReference(gw, svc, r.Scheme)
	})
	return err
}

func (r *SetuGatewayReconciler) updateStatus(
	ctx context.Context, gw *setuv1alpha1.SetuGateway, deployment *appsv1.Deployment, secretHash string,
) error {
	var current appsv1.Deployment
	if err := r.Get(ctx, types.NamespacedName{Name: deployment.Name, Namespace: deployment.Namespace}, &current); err != nil {
		return err
	}

	desired := gw.Spec.Replicas
	if desired == 0 {
		desired = 2
	}

	phase := setuv1alpha1.PhasePending
	switch {
	case current.Status.ReadyReplicas >= desired:
		phase = setuv1alpha1.PhaseReady
	case current.Status.ReadyReplicas > 0:
		phase = setuv1alpha1.PhaseDegraded
	}

	// A status write bumps resourceVersion just like any other update, and this
	// reconciler watches SetuGateway itself - writing status unconditionally on
	// every reconcile re-triggers another reconcile of the same object forever.
	// Only write when something actually changed.
	if gw.Status.Phase == phase &&
		gw.Status.ReadyReplicas == current.Status.ReadyReplicas &&
		gw.Status.ObservedSecretHash == secretHash &&
		gw.Status.ObservedGeneration == gw.Generation {
		return nil
	}

	gw.Status.Phase = phase
	gw.Status.ReadyReplicas = current.Status.ReadyReplicas
	gw.Status.ObservedSecretHash = secretHash
	gw.Status.ObservedGeneration = gw.Generation
	return r.Status().Update(ctx, gw)
}

func hashSecretData(data map[string][]byte) string {
	keys := make([]string, 0, len(data))
	for k := range data {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	h := sha256.New()
	for _, k := range keys {
		h.Write([]byte(k))
		h.Write(data[k])
	}
	return hex.EncodeToString(h.Sum(nil))[:16]
}

// findGatewaysForSecret maps a Secret change back to every SetuGateway in the same
// namespace that references it by name, so editing the Secret alone - with no
// change to the SetuGateway itself - still triggers a reconcile. Without this, the
// secret-rotation behavior in Reconcile() is only ever exercised as a side effect
// of some unrelated SetuGateway-triggered reconcile, not by the secret change that
// is supposed to cause it.
func (r *SetuGatewayReconciler) findGatewaysForSecret(ctx context.Context, secret client.Object) []ctrl.Request {
	var gateways setuv1alpha1.SetuGatewayList
	if err := r.List(ctx, &gateways, client.InNamespace(secret.GetNamespace())); err != nil {
		return nil
	}

	var requests []ctrl.Request
	for _, gw := range gateways.Items {
		if gw.Spec.SecretName == secret.GetName() {
			requests = append(requests, ctrl.Request{NamespacedName: types.NamespacedName{Name: gw.Name, Namespace: gw.Namespace}})
		}
	}
	return requests
}

// SetupWithManager registers this reconciler with the manager, watching SetuGateway
// resources, the Deployments/Services it owns (so an external change to either gets
// reconciled back to the desired state too), and any Secret referenced by a
// SetuGateway's spec.secretName (so rotating a secret's contents actually triggers
// the rolling restart described in Reconcile(), instead of silently doing nothing
// until something else happens to trigger a reconcile).
func (r *SetuGatewayReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&setuv1alpha1.SetuGateway{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Watches(&corev1.Secret{}, handler.EnqueueRequestsFromMapFunc(r.findGatewaysForSecret)).
		Complete(r)
}
