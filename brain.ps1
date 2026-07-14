#!/usr/bin/env pwsh
# hyper-brain: the one command (Windows/PowerShell). See ./brain for POSIX.
#
# A thin, honest orchestration over already-working pieces (ARCHITECTURE.md
# section 13): preflight, terraform apply, build & push the image, seed the index,
# and print how to connect. Re-running converges (terraform is declarative, the
# state bucket bootstrap is create-if-not-exists, the index upserts by hash).
#
# Cloud subcommands (up/down/grant) need gcloud + terraform + Docker and a
# billing-enabled project. Local subcommands (index/ingest/eval/connect/status/
# agent/help) run with no cloud.

[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = "help",
    [string]$Project = "",
    [string]$ProfileName = "personal",
    [string]$Region = "europe-west2",
    [string]$Domains = "",
    [switch]$Wait,
    [switch]$Live,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Infra = Join-Path $Root "infra"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Note($m) { Write-Host "    $m" -ForegroundColor DarkGray }
function Die($m) { Write-Host "Error: $m" -ForegroundColor Red; exit 1 }

# The project's own Python, so local subcommands need no global install.
function Get-Python {
    $venv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
    Die "no Python found. Create the venv first (see README)."
}

function Require-Cmd($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { Die "$name is required. $hint" }
}

# Run a native command whose stderr must not become a terminating error in PS 5.1
# (redirecting a native exe's stderr under ErrorActionPreference=Stop throws).
function Invoke-Quiet([scriptblock]$Block) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Block } finally { $ErrorActionPreference = $previous }
}

# Deploy diagnostics: cloud steps (docker, gcloud) stream their combined output to a
# per-run log as well as the console. In a piped or background run the native tools'
# output would otherwise bypass the transcript, so a failure showed only a bare exit
# code with no cause. With this, the real error is always captured and surfaced.
$Script:DeployLog = $null
function Start-DeployLog {
    $dir = Join-Path $Root ".brain"
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $Script:DeployLog = Join-Path $dir ("deploy-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    "hyper-brain deploy $(Get-Date -Format o)" | Set-Content -Path $Script:DeployLog -Encoding utf8
    Note "Deploy log: $Script:DeployLog"
}

function Show-LogTail {
    if ($Script:DeployLog -and (Test-Path $Script:DeployLog)) {
        Write-Host "    Last lines of $Script:DeployLog :" -ForegroundColor DarkGray
        Get-Content $Script:DeployLog -Tail 25 | ForEach-Object { Write-Host "    | $_" -ForegroundColor DarkGray }
    }
}

# Run a native step (a scriptblock), streaming stdout+stderr to the console and the
# deploy log. On a non-zero exit, print the tail of the log and its path, then exit,
# so the real error is visible even when the run is piped or backgrounded.
#
# `2>&1` merges a native tool's stderr into the pipeline, but in PS 5.1 each stderr line
# becomes an ErrorRecord that PowerShell renders as a red "NativeCommandError" (with an
# "At brain.ps1:.." decoration) even under ErrorActionPreference=Continue. Docker/gcloud/
# terraform write ordinary progress to stderr, so that painted routine output red. Piping
# through ForEach-Object { "$_" } stringifies each item (ErrorRecords -> their plain text)
# onto the success stream, so the same output shows as normal white lines. Exit codes are
# unaffected ($LASTEXITCODE still reflects the native command).
function Invoke-Step([string]$What, [scriptblock]$Block) {
    Note $What
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Script:DeployLog) { & $Block 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $Script:DeployLog -Append }
        else { & $Block 2>&1 | ForEach-Object { "$_" } }
    } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: $What failed (exit code $LASTEXITCODE)." -ForegroundColor Red
        Show-LogTail
        exit 1
    }
}

function Resolve-Project {
    if ($Project) { return $Project }
    if (Get-Command gcloud -ErrorAction SilentlyContinue) {
        $p = Invoke-Quiet { (gcloud config get-value project 2>$null) }
        if ($p -and $p -ne "(unset)") { return $p }
    }
    Die "no project. Pass -Project <id> or run: gcloud config set project <id>"
}

function Tf { param([string[]]$TfArgs) & terraform "-chdir=$Infra" @TfArgs; if ($LASTEXITCODE -ne 0) { Die "terraform failed" } }
function Tf-Output($name) { Invoke-Quiet { (& terraform "-chdir=$Infra" output -raw $name 2>$null) } }

function Print-Mcp($brainUrl) {
    Info "MCP config block (paste into your agent/client):"
    $block = @"
{
  "mcpServers": {
    "hyper-brain": {
      "url": "$brainUrl/mcp",
      "headers": { "Authorization": "Bearer <ID_TOKEN>" }
    }
  }
}
"@
    Write-Host $block
    Note "Get a token with: gcloud auth print-identity-token"
}

# --- Subcommands ---------------------------------------------------------------

function Cmd-Help {
    @"
hyper-brain - one command to a working company brain.

Usage: .\brain.ps1 <command> [-Project id] [-ProfileName personal|controlled] [-Region r]

Cloud commands (need gcloud + terraform + Docker, and a billing-enabled project):
  up            Provision + deploy + seed the brain, then print how to connect.
  down          Tear everything down (terraform destroy).
  grant <email> -Domains a,b   Grant a teammate invoker + domain access.
  review        List documents proposed (via propose_document) awaiting review.
  accept <name> Accept a proposal into its live domain and reindex.

Local commands (no cloud):
  index         Build the local search index from the corpus.
  ingest        Ingest configured sources into the corpus.
  eval          Run the offline agent eval tier.
  platform      Show the AI-platform manifest (model inventory + prompt versions).
  agent [-Live] Chat with the agent locally (adk web). -Live runs the real
                multi-agent team vs the deployed brain (set `$env:BRAIN_TOKEN first).
  ui            Serve the Brain Explorer locally (offline).
  connect       Print the MCP config block for the deployed (or local) brain.
  status        Show what is deployed (or local state).
  preflight     Run the prerequisite checks only.
  version       Print the version.
  help          Show this help.
"@ | Write-Host
}

function Cmd-Version {
    $py = Get-Python
    & $py -c "import tomllib,pathlib;print('hyper-brain',tomllib.loads(pathlib.Path('app/pyproject.toml').read_text())['project']['version'])"
}

function Cmd-Preflight {
    . (Join-Path $Root "scripts\preflight.ps1")
    Invoke-BrainPreflight -Project $Project | Out-Null
}

function Cmd-Index {
    $py = Get-Python
    Info "Building local index from corpus/"
    & $py -m brain_app.indexer.build --corpus corpus --out .brain/index.json
}

function Cmd-Ingest {
    $py = Get-Python
    Info "Ingesting configured sources into corpus/"
    & $py -m brain_app.ingest.run --sources config/sources.yaml --corpus corpus
}

function Cmd-Platform {
    $py = Get-Python
    & $py -m brain_app.inventory
}

function Cmd-Eval {
    $py = Get-Python
    Info "Running the offline eval tier"
    & $py -m pytest app/tests -q -m eval
}

function Cmd-Agent {
    Require-Cmd "adk" "Install the agent extra: pip install -e `".\app[agent]`""
    $agentsDir = Join-Path $Root "app\agents"
    if ($Live) {
        # Live multi-agent team (coordinator -> researcher/curator) against the deployed
        # brain, with Gemini on Vertex. Needs a bearer the brain accepts: copy yours from
        # the signed-in UI (DevTools console: sessionStorage.getItem('hb_access_token'))
        # and set $env:BRAIN_TOKEN before running.
        if (-not $env:BRAIN_TOKEN) { Die "set `$env:BRAIN_TOKEN first (copy it from the signed-in UI: sessionStorage.getItem('hb_access_token'))" }
        $proj = Resolve-Project
        $brainUrl = Tf-Output "brain_url"
        if (-not $brainUrl) { Die "no deployed brain found; run .\brain.ps1 up first" }
        $env:BRAIN_AGENT_MODE = "live"
        $env:BRAIN_URL = "$brainUrl/mcp"
        $env:BRAIN_AUDIENCE = $brainUrl
        $env:GOOGLE_GENAI_USE_VERTEXAI = "true"
        $env:GOOGLE_CLOUD_PROJECT = $proj
        $env:GOOGLE_CLOUD_LOCATION = $Region
        Info "Starting the LIVE multi-agent team (Gemini on Vertex, brain over MCP). Ctrl+C to stop."
    } else {
        $env:BRAIN_AGENT_MODE = "offline"
        Info "Starting the agent dev UI (offline, deterministic). Ctrl+C to stop. Use -Live for the real team."
    }
    Set-Location (Join-Path $Root "app")
    adk web agents
}

function Cmd-Ui {
    $py = Get-Python
    Info "Exporting UI data and serving the Brain Explorer (offline)"
    # If a brain is deployed, bake its real MCP endpoint into the connector modal.
    $exporter = Join-Path $Root "scripts\export_ui_data.py"
    $mcpUrl = ""
    if (Get-Command terraform -ErrorAction SilentlyContinue) { $mcpUrl = Tf-Output "brain_url" }
    if ($mcpUrl) {
        & $py $exporter --profile $ProfileName --mcp-url "$mcpUrl/mcp"
    } else {
        & $py $exporter --profile $ProfileName
    }
    $port = if ($env:BRAIN_UI_PORT) { $env:BRAIN_UI_PORT } else { "8000" }
    Note "Open http://localhost:$port/  (Ctrl+C to stop)"
    Push-Location (Join-Path $Root "ui")
    try { & $py -m http.server $port } finally { Pop-Location }
}

function Cmd-Connect {
    $url = ""
    if (Get-Command terraform -ErrorAction SilentlyContinue) { $url = Tf-Output "brain_url" }
    if (-not $url) {
        $url = $env:BRAIN_URL
        if (-not $url) { $url = "http://localhost:8080" }
        Note "No deployed brain found; showing local/default URL."
    }
    Print-Mcp $url
}

function Cmd-Status {
    if ((Get-Command terraform -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $Infra ".terraform"))) {
        Info "Deployed resources (terraform outputs):"
        & terraform "-chdir=$Infra" output
    }
    else {
        Info "Not deployed. Local state:"
        if (Test-Path (Join-Path $Root ".brain\index.json")) { Note "local index present at .brain/index.json" }
        else { Note "no local index yet (run: .\brain.ps1 index)" }
    }
}

function Cmd-Up {
    Require-Cmd "gcloud" "Install the Google Cloud CLI."
    Require-Cmd "terraform" "Install Terraform."
    Require-Cmd "docker" "Install Docker (to build and push the image)."

    . (Join-Path $Root "scripts\preflight.ps1")
    $proj = Invoke-BrainPreflight -Project $Project
    Start-DeployLog

    # 1. State bucket (create-if-not-exists).
    Info "Bootstrapping the Terraform state bucket"
    & terraform "-chdir=$Infra\bootstrap" init -input=false | Out-Null
    & terraform "-chdir=$Infra\bootstrap" apply -auto-approve -var "project_id=$proj" -var "region=$Region"
    if ($LASTEXITCODE -ne 0) { Die "bootstrap failed" }
    $stateBucket = (& terraform "-chdir=$Infra\bootstrap" output -raw state_bucket)

    # 2. Provision (first apply uses placeholder images so the registry exists).
    Info "Provisioning infrastructure ($ProfileName profile)"
    & terraform "-chdir=$Infra" init -input=false -reconfigure "-backend-config=bucket=$stateBucket" | Out-Null
    Tf @("apply", "-auto-approve", "-var-file=../config/$ProfileName.tfvars", "-var", "project_id=$proj", "-var", "region=$Region")

    # 3. Build & push the three images (brain, agent, ui). The jobs reuse the brain
    #    image with an args override.
    $repo = "$Region-docker.pkg.dev/$proj/brain-images"
    $brainImage = "$repo/brain:latest"
    $agentImage = "$repo/agent:latest"
    $uiImage = "$repo/ui:latest"
    $py = Get-Python
    Info "Building and pushing images to $repo"
    Invoke-Step "Configuring docker credentials" { gcloud auth configure-docker "$Region-docker.pkg.dev" --quiet }
    Invoke-Step "Building brain image" { docker build -t $brainImage -f (Join-Path $Root "app\Dockerfile") (Join-Path $Root "app") }
    Invoke-Step "Building agent image" { docker build -t $agentImage -f (Join-Path $Root "app\Dockerfile.agent") (Join-Path $Root "app") }
    # The services exist after the first apply, so bake their live URLs into the SPA:
    # the MCP endpoint (connector modal), and the OAuth issuer + REST base the live app
    # signs in against and calls.
    $brainUrl = Tf-Output "brain_url"
    $authUrl = Tf-Output "auth_url"
    if ($brainUrl) {
        & $py (Join-Path $Root "scripts\export_ui_data.py") --profile $ProfileName `
            --mcp-url "$brainUrl/mcp" --api-url "$brainUrl" --auth-url "$authUrl"
    } else {
        & $py (Join-Path $Root "scripts\export_ui_data.py") --profile $ProfileName
    }
    Invoke-Step "Building ui image" { docker build -t $uiImage (Join-Path $Root "ui") }
    foreach ($img in @($brainImage, $agentImage, $uiImage)) { Invoke-Step "Pushing $img" { docker push $img } }

    # 4. Upload the corpus so the index Job can build in-tenancy, then roll out the
    #    real images and set the brain's own URL as the OIDC audience.
    $corpusBucket = Tf-Output "corpus_bucket"
    Info "Uploading corpus to gs://$corpusBucket"
    Invoke-Step "Syncing corpus to gs://$corpusBucket" { gcloud storage rsync -r (Join-Path $Root "corpus") "gs://$corpusBucket" --quiet }
    $brainUrl = Tf-Output "brain_url"
    $authUrl = Tf-Output "auth_url"
    $uiUrl = Tf-Output "ui_url"
    Tf @("apply", "-auto-approve", "-var-file=../config/$ProfileName.tfvars", "-var", "project_id=$proj", "-var", "region=$Region",
        "-var", "image_brain=$brainImage", "-var", "image_indexer=$brainImage", "-var", "image_ingest=$brainImage",
        "-var", "image_agent=$agentImage", "-var", "image_ui=$uiImage", "-var", "brain_audience=$brainUrl",
        "-var", "auth_audience=$authUrl", "-var", "ui_origin=$uiUrl")

    # 5. Build the index in-tenancy (Vertex embeddings) via the Cloud Run Job.
    $prefix = Tf-Output "name_prefix"
    Info "Running the index job (in-tenancy build to gs://$(Tf-Output 'index_bucket'))"
    Invoke-Quiet {
        if ($Script:DeployLog) { gcloud run jobs execute "$prefix-indexer" --project $proj --region $Region --wait 2>&1 | Tee-Object -FilePath $Script:DeployLog -Append | Out-Null }
        else { gcloud run jobs execute "$prefix-indexer" --project $proj --region $Region --wait 2>&1 | Out-Null }
    }
    if ($LASTEXITCODE -ne 0) { Note "index job did not complete; see the deploy log or run: gcloud run jobs executions list --job $prefix-indexer" }

    # 6. Report.
    Info "Done. Your brain is live."
    Note "brain: $brainUrl"
    Note "agent: $(Tf-Output 'agent_url')"
    Note "ui:    $(Tf-Output 'ui_url')"
    if ($authUrl) { Note "auth:  $authUrl  (OAuth AS -- see README to enable remote connectors)" }
    Print-Mcp $brainUrl
}

function Cmd-Down {
    Require-Cmd "terraform" "Install Terraform."
    $proj = Resolve-Project
    Info "Tearing down the $ProfileName stack"
    Tf @("destroy", "-auto-approve", "-var-file=../config/$ProfileName.tfvars", "-var", "project_id=$proj", "-var", "region=$Region")
    Info "Done. Residual cost is only bucket/registry storage (pennies)."
}

function Cmd-Grant {
    Require-Cmd "gcloud" "Install the Google Cloud CLI."
    $email = if ($Rest.Count -ge 1) { $Rest[0] } else { "" }
    if (-not $email) { Die "usage: .\brain.ps1 grant <email> -Domains a,b" }
    if (-not $Domains) { Die "specify -Domains a,b (the domains this person may retrieve)" }
    $proj = Resolve-Project
    $prefix = Tf-Output "name_prefix"
    if (-not $prefix) { $prefix = "brain" }
    Info "Granting $email invoker access on the brain, agent and UI"
    foreach ($svc in @("brain", "agent", "ui")) {
        Invoke-Quiet {
            gcloud run services add-iam-policy-binding "$prefix-$svc" `
                --project $proj --region $Region `
                --member "user:$email" --role "roles/run.invoker" --quiet 2>$null
        }
    }
    Info "Now add $email to the domain ACL. Edit config/$ProfileName.policy.yaml, add a"
    Note "grant for principal 'user:$email' with domains: [$Domains], then upload it so the"
    Note "brain picks it up within ~30s (no rebuild):"
    Note "  gcloud storage cp config/$ProfileName.policy.yaml gs://$(Tf-Output 'index_bucket')/policy.yaml"
}

# Review and accept documents proposed through the gated write path. propose_document
# stages a proposal under proposals/ in the corpus bucket; review lists them, accept
# promotes one into its live domain folder and reruns the index job.
function Cmd-Review {
    Require-Cmd "gcloud" "Install the Google Cloud CLI."
    $py = Get-Python
    $corpus = Tf-Output "corpus_bucket"
    if (-not $corpus) { Die "no deployed corpus bucket found; run .\brain.ps1 up first" }
    & $py -m brain_app.serving.review list --bucket $corpus
}

function Cmd-Accept {
    Require-Cmd "gcloud" "Install the Google Cloud CLI."
    $name = if ($Rest.Count -ge 1) { $Rest[0] } else { "" }
    if (-not $name) { Die "usage: .\brain.ps1 accept <proposal-name>  (see .\brain.ps1 review)" }
    $py = Get-Python
    $proj = Resolve-Project
    $corpus = Tf-Output "corpus_bucket"
    if (-not $corpus) { Die "no deployed corpus bucket found; run .\brain.ps1 up first" }
    $prefix = Tf-Output "name_prefix"
    if (-not $prefix) { $prefix = "brain" }
    $waitArg = @(); if ($Wait) { $waitArg = @("--wait") }
    & $py -m brain_app.serving.review accept --bucket $corpus --name $name `
        --indexer-job "$prefix-indexer" --project $proj --region $Region @waitArg
}

# --- Dispatch ------------------------------------------------------------------

try {
    switch ($Command.ToLower()) {
        "help" { Cmd-Help }
        "-h" { Cmd-Help }
        "--help" { Cmd-Help }
        "version" { Cmd-Version }
        "preflight" { Cmd-Preflight }
        "index" { Cmd-Index }
        "ingest" { Cmd-Ingest }
        "eval" { Cmd-Eval }
        "platform" { Cmd-Platform }
        "agent" { Cmd-Agent }
        "ui" { Cmd-Ui }
        "connect" { Cmd-Connect }
        "status" { Cmd-Status }
        "up" { Cmd-Up }
        "down" { Cmd-Down }
        "grant" { Cmd-Grant }
        "review" { Cmd-Review }
        "accept" { Cmd-Accept }
        default { Die "unknown command '$Command'. Run: .\brain.ps1 help" }
    }
}
catch {
    # Preflight and other steps signal failure by throwing after printing a clean,
    # actionable message; exit non-zero without dumping a PowerShell stack trace.
    exit 1
}
