# Honest-prerequisites gate for `brain up` (Windows/PowerShell parity with
# preflight.sh; ARCHITECTURE.md section 13). Dot-sourced by brain.ps1.
#
# Invoke-BrainPreflight checks the required CLIs, gcloud auth (user + ADC), a
# selected project and billing. On any failure it prints the EXACT remediation and
# throws. On success it returns the resolved project id (the only value written to
# the output stream). Provisioning roles are not pre-checked here: gcloud has no
# clean per-permission test, and `terraform apply` reports any missing role exactly.

function Invoke-BrainPreflight {
    param([string]$Project = "")

    function Fail($problem, $fix) {
        Write-Host ""
        Write-Host "Preflight failed: $problem" -ForegroundColor Red
        Write-Host "  Fix: $fix" -ForegroundColor Cyan
        Write-Host ""
        throw "preflight failed"
    }

    # Run gcloud without letting its stderr become a terminating error in PS 5.1.
    # Returns an object with the exit Code and trimmed Text output.
    function RunGcloud {
        param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GcArgs)
        $previous = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $text = (& gcloud @GcArgs 2>&1 | Out-String)
            [pscustomobject]@{ Code = $LASTEXITCODE; Text = $text.Trim() }
        }
        finally { $ErrorActionPreference = $previous }
    }

    # 1. Required CLIs.
    if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
        Fail "the gcloud CLI is not installed." "install it: https://cloud.google.com/sdk/docs/install"
    }
    if (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
        Fail "terraform is not installed." "install it: https://developer.hashicorp.com/terraform/install"
    }

    # 2. User authentication.
    $active = RunGcloud auth list --filter=status:ACTIVE --format="value(account)"
    if ($active.Code -ne 0 -or -not $active.Text) {
        Fail "gcloud has no active account." "gcloud auth login"
    }

    # 3. Application Default Credentials (Terraform and the SDKs use these). A
    #    print-access-token also surfaces an expired session that needs re-login.
    $adc = RunGcloud auth application-default print-access-token
    if ($adc.Code -ne 0) {
        Fail "no valid Application Default Credentials (they may have expired)." `
            "gcloud auth application-default login"
    }

    # 4. A project is selected (argument wins, else gcloud config).
    if (-not $Project) {
        $configured = RunGcloud config get-value project
        if ($configured.Code -eq 0) { $Project = $configured.Text }
    }
    if (-not $Project -or $Project -eq "(unset)") {
        Fail "no project selected." "gcloud config set project <YOUR_PROJECT_ID>  (or pass -Project)"
    }

    # 5. The project is reachable by this caller.
    $describe = RunGcloud projects describe $Project --format="value(projectId)"
    if ($describe.Code -ne 0) {
        Fail "project '$Project' not found or not accessible." "check the id, or request access to '$Project'"
    }

    # 6. Billing enabled.
    $billing = RunGcloud billing projects describe $Project --format="value(billingEnabled)"
    if ($billing.Text -ne "True") {
        Fail "billing is not enabled on '$Project'." `
            "gcloud billing projects link $Project --billing-account <ACCOUNT_ID>"
    }

    Write-Host "Preflight OK for project $Project" -ForegroundColor Green
    Write-Host "  (provisioning roles are verified by 'terraform apply', which names any missing role.)" -ForegroundColor DarkGray
    return $Project
}
