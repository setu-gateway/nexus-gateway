{{/*
Chart name and version label, truncated to fit Kubernetes' 63-char label limit.
*/}}
{{- define "setu-gateway.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "setu-gateway.fullname" -}}
{{- .Release.Name }}
{{- end }}

{{- define "setu-gateway.labels" -}}
helm.sh/chart: {{ include "setu-gateway.chart" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: setu-gateway
{{- end }}

{{- define "setu-gateway.gatewayName" -}}
{{ include "setu-gateway.fullname" . }}-gateway
{{- end }}

{{- define "setu-gateway.gatewaySelectorLabels" -}}
app.kubernetes.io/name: {{ include "setu-gateway.gatewayName" . }}
{{- end }}

{{- define "setu-gateway.dashboardName" -}}
{{ include "setu-gateway.fullname" . }}-dashboard
{{- end }}

{{- define "setu-gateway.dashboardSelectorLabels" -}}
app.kubernetes.io/name: {{ include "setu-gateway.dashboardName" . }}
{{- end }}

{{/*
Name of the Secret the gateway reads its DATABASE_URL/REDIS_URL/JWT_SECRET/provider
keys from - either the user's own pre-existing Secret, or the one this chart renders.
*/}}
{{- define "setu-gateway.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "setu-gateway.fullname" .) }}
{{- end }}
{{- end }}
