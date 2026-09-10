$ErrorActionPreference = "Stop"

$composeFiles = @(
    "-p", "docflow-test",
    "-f", "compose.test.yml"
)

try {
    & docker compose @composeFiles up `
        --build `
        --abort-on-container-exit `
        --exit-code-from backend-tests
    $testExitCode = $LASTEXITCODE
}
finally {
    & docker compose @composeFiles down --volumes --remove-orphans
}

exit $testExitCode

