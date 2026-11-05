# DWCT Studio Mobile (Android MVP)

Android-first Expo / React Native client for the existing DWCT Generative Sound Studio FastAPI backend.

## Local development

From `mobile/android`:

```powershell
npm install
npx expo install --fix
npx expo start
```

Open the app using an Android device with Expo Go or an Android emulator. For a development build, use the Expo development-build workflow.

Enter the HTTPS URL of a reachable backend and optionally a bearer token. The current MVP tests `GET /health/` and displays the JSON response.

**Security:** Never put tokens in the repository, expose the backend directly over the public internet, or bypass TLS certificate verification. The token is stored using Expo SecureStore after a connection attempt. The server must independently enforce authentication on sensitive endpoints. Health may be intentionally public; a successful health check is not proof that the generation API is authenticated or available.

## Next steps

1. Inspect the active backend's auth and generation API contracts.
2. Add a secure API client and project list.
3. Add audio picker/upload and job submission.
4. Poll or stream render progress and display previews.
5. Add CI typecheck and Android build pipeline.

This scaffold does not yet generate videos or produce an APK.
