package support

import (
	"path/filepath"
	"testing"
)

func TestDefaultStoragePaths(t *testing.T) {
	home := filepath.Join("D:\\", "EDMG-Studio")
	paths := DefaultStoragePaths(home)

	if paths.DataDir != filepath.Join(home, "data") {
		t.Fatalf("expected data dir under studio home, got %s", paths.DataDir)
	}
	if paths.OllamaModelsDir != filepath.Join(home, "models", "ollama") {
		t.Fatalf("expected Ollama models dir under models root, got %s", paths.OllamaModelsDir)
	}
	if paths.ElectronUserData != filepath.Join(home, "electron") {
		t.Fatalf("expected electron user data under studio home, got %s", paths.ElectronUserData)
	}
}

func TestResolveStoragePathsWithOverrides(t *testing.T) {
	home := filepath.Join("D:\\", "EDMG-Studio")
	cfg := BootstrapConfig{
		StudioHome: home,
		StorageSettings: StorageOverrides{
			CacheRoot: filepath.Join(home, "cache-alt"),
			LogsDir:   filepath.Join(home, "logs-alt"),
		},
	}

	paths := ResolveStoragePaths(home, cfg)
	if paths.CacheRoot != filepath.Join(home, "cache-alt") {
		t.Fatalf("expected cache override, got %s", paths.CacheRoot)
	}
	if paths.LogsDir != filepath.Join(home, "logs-alt") {
		t.Fatalf("expected logs override, got %s", paths.LogsDir)
	}
	if paths.ModelsDir != filepath.Join(home, "models") {
		t.Fatalf("expected default models dir, got %s", paths.ModelsDir)
	}
}
