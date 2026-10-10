# Foundry Director endpoint

The Azure Cosmos video option and Foundry project metadata card have been replaced in native WinUI Settings by **Foundry Director endpoint**. Azure Cosmos is no longer advertised in the render provider list or native video route selector.

1. In Settings, enter the Foundry chat URL or base URL and exact model deployment name.
2. Save the resource key in Secrets as `foundry_director_api_key` (or explicitly configure `EDMG_FOUNDRY_DIRECTOR_API_KEY` for the backend).
3. Click **Use Foundry for Director**. This selects the existing server Director route and preserves specialist settings.
4. Generate a Director draft in Director or Workspace. Review and apply it before rendering with your selected video renderer.

A full `/openai/v1/chat/completions` URL is normalized to its base URL. Bare Azure resource URLs use `/openai/v1`. The dedicated key is resolved only for HTTPS Azure inference hosts; NVIDIA credentials are not substituted. Save/configuration does not prove successful inference. Existing Azure video credentials are not migrated because the prior key returned HTTP 401.

The updated app/backend must be restarted to load these changes. No live Foundry inference was run for this replacement.
