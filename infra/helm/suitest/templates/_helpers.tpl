{{/*
Common labels + naming helpers.
*/}}

{{- define "suitest.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "suitest.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "suitest.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "suitest.labels" -}}
helm.sh/chart: {{ include "suitest.chart" . }}
app.kubernetes.io/name: {{ include "suitest.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
suitest.dev/tier: {{ .Values.suitest.tier | quote }}
{{- end -}}

{{- define "suitest.selectorLabels" -}}
app.kubernetes.io/name: {{ include "suitest.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "suitest.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "suitest.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
