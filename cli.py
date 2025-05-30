import typer
import httpx


def generate(url: str, output: str):
    print(url, output)
    """
       Download and save generated client code from a running FastAPI server.
       """
    if not url.endswith("/fastroutes"):
        client_url = url.rstrip("/") + "/fastroutes"
    else:
        client_url = url

    try:
        response = httpx.get(client_url)
        response.raise_for_status()
        with open(output, "wb") as f:
            f.write(response.content)
        typer.secho(f"✅ File saved to {output}", fg=typer.colors.GREEN)
    except httpx.HTTPError as e:
        typer.secho(f"❌ Failed to fetch client code: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    typer.run(generate)