# Loop every 10m: continue indonesia-intel MCP phases
$ErrorActionPreference = "Continue"
while ($true) {
  Start-Sleep -Seconds 600
  $payload = @{
    prompt = "Continue Trellis task 查资料/07-28-indonesia-intel-mcp-server: read execution-plan.md Active phase; if pending phases remain execute next phase to GREEN; if phases 1-3 complete stop; skip Phase 4 unless needed"
  } | ConvertTo-Json -Compress
  Write-Output ("AGENT_LOOP_TICK_indonesia_intel_mcp " + $payload)
}
