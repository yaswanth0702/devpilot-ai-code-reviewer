# Deploy the browser reviewer

The browser, file upload, and review chat run in the Python service. For a public demo, select the offline provider. It exercises the approval flow without using a personal API key. GitHub reviews and fix pull requests use the separate GitHub setup described in the [README](../README.md).

## Railway

1. Create a service from this repository. Set **Root Directory** to `/agent`. Railway builds the Dockerfile in that directory. Under **Deploy**, set the health check path to `/health` and its timeout to 60 seconds.
2. Set the service variable `DEVPILOT_PROVIDER=mock` and deploy one replica. Leave the start command empty so the image starts Uvicorn on Railway's assigned port.
3. Generate a public domain for the service. Open `/health` on that domain and check that the response has `"status":"ok"` and `"provider":"mock"`.
4. Open the service home page and review this snippet as `Role.java`. Inspect the proposed change, ask about the finding, then approve and download the corrected file.

```java
class Role {
    boolean isAdmin(String role) {
        return role == "admin";
    }
}
```

The demo catches a small set of patterns, including this Java string comparison. For model-backed reviews of other code, run the service locally or behind authenticated access. Set `DEVPILOT_PROVIDER` and the matching provider key in that service's environment. A public demo needs no GitHub token.

## Run the same image locally

From the repository root:

```sh
docker build -t devpilot-web ./agent
docker run --rm -e DEVPILOT_PROVIDER=mock -e PORT=8100 -p 127.0.0.1:8100:8100 devpilot-web
```

Open [the browser reviewer](http://127.0.0.1:8100). The server defaults to port 8000 when `PORT` is unset.
