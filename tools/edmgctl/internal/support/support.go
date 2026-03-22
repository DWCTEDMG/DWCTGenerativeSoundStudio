package support

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

const (
	AppName         = "EDMG Studio"
	StudioRelDir    = "studio/edmg-studio"
	BootstrapFile   = "bootstrap.json"
	PackageJSON     = "package.json"
	BackendRelDir   = "electron-resources/backend"
	FFmpegRelDir    = "electron-resources/bin"
	BootstrapRelDir = "EDMG Studio"
)

var (
	supportedPythonMin          = [2]int{3, 10}
	supportedPythonMaxExclusive = [2]int{3, 14}
	defaultStorageRelativePaths = map[string]string{
		"dataDir":     "data",
		"modelsDir":   "models",
		"cacheRoot":   "cache",
		"logsDir":     "logs",
		"externalDir": "external",
	}
)

type PackageMeta struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

type ToolStatus struct {
	Name    string `json:"name"`
	Found   bool   `json:"found"`
	Path    string `json:"path,omitempty"`
	Version string `json:"version,omitempty"`
	Note    string `json:"note,omitempty"`
}

type GitStatus struct {
	Available bool     `json:"available"`
	Head      string   `json:"head,omitempty"`
	Branch    string   `json:"branch,omitempty"`
	Clean     bool     `json:"clean"`
	Dirty     []string `json:"dirty,omitempty"`
	Note      string   `json:"note,omitempty"`
}

type StorageOverrides struct {
	DataDir     string `json:"dataDir,omitempty"`
	ModelsDir   string `json:"modelsDir,omitempty"`
	CacheRoot   string `json:"cacheRoot,omitempty"`
	LogsDir     string `json:"logsDir,omitempty"`
	ExternalDir string `json:"externalDir,omitempty"`
}

type AISettings struct {
	Mode                string `json:"mode,omitempty"`
	Provider            string `json:"provider,omitempty"`
	AIBaseURL           string `json:"aiBaseUrl,omitempty"`
	OllamaURL           string `json:"ollamaUrl,omitempty"`
	OllamaModel         string `json:"ollamaModel,omitempty"`
	OpenAICompatBaseURL string `json:"openaiCompatBaseUrl,omitempty"`
	OpenAICompatModel   string `json:"openaiCompatModel,omitempty"`
}

type LastMigration struct {
	OK      *bool  `json:"ok,omitempty"`
	Reason  string `json:"reason,omitempty"`
	Message string `json:"message,omitempty"`
}

type BootstrapConfig struct {
	StudioHome       string           `json:"studioHome,omitempty"`
	StorageSettings  StorageOverrides `json:"storageSettings,omitempty"`
	AISettings       AISettings       `json:"aiSettings,omitempty"`
	PendingMigration any              `json:"pendingMigration,omitempty"`
	LastMigration    *LastMigration   `json:"lastMigration,omitempty"`
}

type StoragePaths struct {
	StudioHome       string `json:"studioHome"`
	DataDir          string `json:"dataDir"`
	ModelsDir        string `json:"modelsDir"`
	CacheRoot        string `json:"cacheRoot"`
	LogsDir          string `json:"logsDir"`
	ExternalDir      string `json:"externalDir"`
	ElectronUserData string `json:"electronUserData"`
	SessionData      string `json:"sessionData"`
	OllamaModelsDir  string `json:"ollamaModelsDir"`
}

type BootstrapReport struct {
	Path              string          `json:"path"`
	Exists            bool            `json:"exists"`
	Config            BootstrapConfig `json:"config"`
	Resolved          StoragePaths    `json:"resolved"`
	OutsideStudioHome []string        `json:"outsideStudioHome,omitempty"`
	PendingMigration  bool            `json:"pendingMigration"`
	LastMigrationOK   *bool           `json:"lastMigrationOk,omitempty"`
}

type ArtifactStatus struct {
	Label  string `json:"label"`
	Path   string `json:"path"`
	Exists bool   `json:"exists"`
}

type ReleaseStatus struct {
	StudioDir          string           `json:"studioDir"`
	Package            PackageMeta      `json:"package"`
	WindowsReleaseHost bool             `json:"windowsReleaseHost"`
	BundleManifestPath string           `json:"bundleManifestPath"`
	BundleManifestOK   bool             `json:"bundleManifestOk"`
	BundleSourceHash   string           `json:"bundleSourceHash,omitempty"`
	Artifacts          []ArtifactStatus `json:"artifacts"`
}

type DoctorReport struct {
	Platform  string          `json:"platform"`
	RepoRoot  string          `json:"repoRoot"`
	StudioDir string          `json:"studioDir"`
	Package   PackageMeta     `json:"package"`
	Git       GitStatus       `json:"git"`
	Tools     []ToolStatus    `json:"tools"`
	Bootstrap BootstrapReport `json:"bootstrap"`
	Release   ReleaseStatus   `json:"release"`
	Warnings  []string        `json:"warnings,omitempty"`
}

func FindRepoRoot(start string) (string, error) {
	if start == "" {
		start = "."
	}
	current, err := filepath.Abs(start)
	if err != nil {
		return "", err
	}

	for {
		studioPackage := filepath.Join(current, StudioRelDir, PackageJSON)
		gitDir := filepath.Join(current, ".git")
		if fileExists(studioPackage) && pathExists(gitDir) {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			break
		}
		current = parent
	}

	return "", fmt.Errorf("could not find repo root from %s", start)
}

func LoadPackageMeta(repoRoot string) (PackageMeta, error) {
	packagePath := filepath.Join(repoRoot, StudioRelDir, PackageJSON)
	var meta PackageMeta
	data, err := os.ReadFile(packagePath)
	if err != nil {
		return meta, err
	}
	if err := json.Unmarshal(data, &meta); err != nil {
		return meta, err
	}
	if meta.Name == "" || meta.Version == "" {
		return meta, fmt.Errorf("package metadata incomplete in %s", packagePath)
	}
	return meta, nil
}

func CollectDoctorReport(repoRoot string) (DoctorReport, error) {
	repoRoot, err := FindRepoRoot(repoRoot)
	if err != nil {
		return DoctorReport{}, err
	}
	studioDir := filepath.Join(repoRoot, StudioRelDir)
	pkg, err := LoadPackageMeta(repoRoot)
	if err != nil {
		return DoctorReport{}, err
	}

	bootstrap, err := ReadBootstrapReport()
	if err != nil {
		return DoctorReport{}, err
	}
	release, err := CollectReleaseStatus(repoRoot)
	if err != nil {
		return DoctorReport{}, err
	}

	warnings := make([]string, 0, 6)
	if len(bootstrap.OutsideStudioHome) > 0 {
		warnings = append(warnings, fmt.Sprintf("storage roots escape Studio Home: %s", strings.Join(bootstrap.OutsideStudioHome, ", ")))
	}
	if !release.BundleManifestOK {
		warnings = append(warnings, "backend bundle manifest missing or unreadable")
	}
	for _, artifact := range release.Artifacts {
		if !artifact.Exists {
			warnings = append(warnings, fmt.Sprintf("missing artifact: %s", artifact.Label))
		}
	}
	if !release.WindowsReleaseHost {
		warnings = append(warnings, "current host is not Windows; dist:win may not be runnable here")
	}

	return DoctorReport{
		Platform:  runtime.GOOS + "/" + runtime.GOARCH,
		RepoRoot:  repoRoot,
		StudioDir: studioDir,
		Package:   pkg,
		Git:       CollectGitStatus(repoRoot),
		Tools:     CollectToolStatus(),
		Bootstrap: bootstrap,
		Release:   release,
		Warnings:  warnings,
	}, nil
}

func CollectToolStatus() []ToolStatus {
	tools := []ToolStatus{
		versionedTool("git", []commandCandidate{{Name: "git"}}),
		versionedTool("node", []commandCandidate{{Name: "node"}}),
		versionedTool("npm", []commandCandidate{{Name: npmCommandName()}}),
		pythonToolStatus(),
		{
			Name:    "go",
			Found:   true,
			Path:    executableOrBlank(),
			Version: runtime.Version(),
			Note:    "support-plane CLI toolchain",
		},
	}
	return tools
}

func CollectGitStatus(repoRoot string) GitStatus {
	git := resolveCommand([]commandCandidate{{Name: "git"}})
	if git.Path == "" {
		return GitStatus{Clean: true, Note: "git not found"}
	}

	head := strings.TrimSpace(runAndCapture(repoRoot, git.Path, "rev-parse", "--short", "HEAD"))
	branch := strings.TrimSpace(runAndCapture(repoRoot, git.Path, "rev-parse", "--abbrev-ref", "HEAD"))
	statusOutput := strings.TrimSpace(runAndCapture(repoRoot, git.Path, "status", "--porcelain"))

	status := GitStatus{
		Available: true,
		Head:      head,
		Branch:    branch,
		Clean:     statusOutput == "",
	}

	if statusOutput != "" {
		lines := strings.Split(statusOutput, "\n")
		status.Dirty = make([]string, 0, len(lines))
		for _, line := range lines {
			if strings.TrimSpace(line) == "" {
				continue
			}
			status.Dirty = append(status.Dirty, strings.TrimSpace(line))
		}
	}
	return status
}

func CollectReleaseStatus(repoRoot string) (ReleaseStatus, error) {
	repoRoot, err := FindRepoRoot(repoRoot)
	if err != nil {
		return ReleaseStatus{}, err
	}
	studioDir := filepath.Join(repoRoot, StudioRelDir)
	pkg, err := LoadPackageMeta(repoRoot)
	if err != nil {
		return ReleaseStatus{}, err
	}

	manifestPath := filepath.Join(studioDir, BackendRelDir, "backend-bundle-manifest.json")
	manifestHash := ""
	manifestOK := false
	if data, err := os.ReadFile(manifestPath); err == nil {
		var payload struct {
			SourceHash string `json:"sourceHash"`
		}
		if json.Unmarshal(data, &payload) == nil {
			manifestOK = true
			manifestHash = payload.SourceHash
		}
	}

	artifacts := []ArtifactStatus{
		{
			Label:  "backend bundle",
			Path:   firstExisting(filepath.Join(studioDir, BackendRelDir, "edmg-studio-backend.exe"), filepath.Join(studioDir, BackendRelDir, "edmg-studio-backend")),
			Exists: fileExists(filepath.Join(studioDir, BackendRelDir, "edmg-studio-backend.exe")) || fileExists(filepath.Join(studioDir, BackendRelDir, "edmg-studio-backend")),
		},
		{
			Label:  "bundled ffmpeg",
			Path:   firstExisting(filepath.Join(studioDir, FFmpegRelDir, "ffmpeg.exe"), filepath.Join(studioDir, FFmpegRelDir, "ffmpeg")),
			Exists: fileExists(filepath.Join(studioDir, FFmpegRelDir, "ffmpeg.exe")) || fileExists(filepath.Join(studioDir, FFmpegRelDir, "ffmpeg")),
		},
		{
			Label:  "win-unpacked app",
			Path:   filepath.Join(studioDir, "dist", "win-unpacked", packagedAppName()),
			Exists: fileExists(filepath.Join(studioDir, "dist", "win-unpacked", packagedAppName())),
		},
		{
			Label:  "installer",
			Path:   filepath.Join(studioDir, "dist", fmt.Sprintf("%s Setup %s.exe", pkg.Name, pkg.Version)),
			Exists: fileExists(filepath.Join(studioDir, "dist", fmt.Sprintf("%s Setup %s.exe", pkg.Name, pkg.Version))),
		},
	}

	return ReleaseStatus{
		StudioDir:          studioDir,
		Package:            pkg,
		WindowsReleaseHost: runtime.GOOS == "windows",
		BundleManifestPath: manifestPath,
		BundleManifestOK:   manifestOK,
		BundleSourceHash:   manifestHash,
		Artifacts:          artifacts,
	}, nil
}

func ReadBootstrapReport() (BootstrapReport, error) {
	bootstrapPath, err := BootstrapConfigPath()
	if err != nil {
		return BootstrapReport{}, err
	}
	report := BootstrapReport{
		Path: bootstrapPath,
	}

	if !fileExists(bootstrapPath) {
		report.Resolved = DefaultStoragePaths(filepath.Dir(bootstrapPath))
		return report, nil
	}

	report.Exists = true
	data, err := os.ReadFile(bootstrapPath)
	if err != nil {
		return report, err
	}
	if err := json.Unmarshal(data, &report.Config); err != nil {
		return report, err
	}

	fallbackHome := filepath.Dir(bootstrapPath)
	report.Resolved = ResolveStoragePaths(fallbackHome, report.Config)
	report.PendingMigration = report.Config.PendingMigration != nil
	if report.Config.LastMigration != nil {
		report.LastMigrationOK = report.Config.LastMigration.OK
	}

	for label, candidate := range map[string]string{
		"dataDir":     report.Resolved.DataDir,
		"modelsDir":   report.Resolved.ModelsDir,
		"cacheRoot":   report.Resolved.CacheRoot,
		"logsDir":     report.Resolved.LogsDir,
		"externalDir": report.Resolved.ExternalDir,
	} {
		if !pathWithin(report.Resolved.StudioHome, candidate) {
			report.OutsideStudioHome = append(report.OutsideStudioHome, label)
		}
	}

	return report, nil
}

func BootstrapConfigPath() (string, error) {
	configDir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(configDir, BootstrapRelDir, BootstrapFile), nil
}

func DefaultStoragePaths(studioHome string) StoragePaths {
	studioHome = cleanPath(studioHome)
	if studioHome == "" {
		studioHome = "."
	}
	electronUserData := filepath.Join(studioHome, "electron")
	return StoragePaths{
		StudioHome:       studioHome,
		DataDir:          filepath.Join(studioHome, defaultStorageRelativePaths["dataDir"]),
		ModelsDir:        filepath.Join(studioHome, defaultStorageRelativePaths["modelsDir"]),
		CacheRoot:        filepath.Join(studioHome, defaultStorageRelativePaths["cacheRoot"]),
		LogsDir:          filepath.Join(studioHome, defaultStorageRelativePaths["logsDir"]),
		ExternalDir:      filepath.Join(studioHome, defaultStorageRelativePaths["externalDir"]),
		ElectronUserData: electronUserData,
		SessionData:      filepath.Join(electronUserData, "session"),
		OllamaModelsDir:  filepath.Join(studioHome, defaultStorageRelativePaths["modelsDir"], "ollama"),
	}
}

func ResolveStoragePaths(fallbackHome string, cfg BootstrapConfig) StoragePaths {
	studioHome := cleanPath(cfg.StudioHome)
	if studioHome == "" {
		studioHome = cleanPath(fallbackHome)
	}

	paths := DefaultStoragePaths(studioHome)
	if override := cleanPath(cfg.StorageSettings.DataDir); override != "" {
		paths.DataDir = override
	}
	if override := cleanPath(cfg.StorageSettings.ModelsDir); override != "" {
		paths.ModelsDir = override
	}
	if override := cleanPath(cfg.StorageSettings.CacheRoot); override != "" {
		paths.CacheRoot = override
	}
	if override := cleanPath(cfg.StorageSettings.LogsDir); override != "" {
		paths.LogsDir = override
	}
	if override := cleanPath(cfg.StorageSettings.ExternalDir); override != "" {
		paths.ExternalDir = override
	}
	paths.OllamaModelsDir = filepath.Join(paths.ModelsDir, "ollama")
	return paths
}

func RunReleaseBuild(repoRoot string) error {
	return runNPMScript(repoRoot, "dist:win")
}

func RunReleaseValidate(repoRoot string) error {
	return runNPMScript(repoRoot, "validate:release")
}

func runNPMScript(repoRoot, script string) error {
	repoRoot, err := FindRepoRoot(repoRoot)
	if err != nil {
		return err
	}
	npm := resolveCommand([]commandCandidate{{Name: npmCommandName()}})
	if npm.Path == "" {
		return errors.New("npm not found in PATH")
	}
	cmd := exec.Command(npm.Path, "run", script)
	cmd.Dir = filepath.Join(repoRoot, StudioRelDir)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Stdin = os.Stdin
	return cmd.Run()
}

type commandCandidate struct {
	Name string
	Args []string
}

type resolvedCommand struct {
	Path string
	Args []string
}

func versionedTool(name string, candidates []commandCandidate) ToolStatus {
	resolved := resolveCommand(candidates)
	if resolved.Path == "" {
		return ToolStatus{Name: name, Found: false}
	}
	args := append([]string{}, resolved.Args...)
	switch name {
	case "git":
		args = append(args, "--version")
	case "node":
		args = append(args, "--version")
	case "npm":
		args = append(args, "--version")
	default:
		args = append(args, "--version")
	}
	return ToolStatus{
		Name:    name,
		Found:   true,
		Path:    resolved.Path,
		Version: strings.TrimSpace(runAndCapture("", resolved.Path, args...)),
	}
}

func pythonToolStatus() ToolStatus {
	candidates := []commandCandidate{{Name: "python"}}
	if runtime.GOOS == "windows" {
		candidates = append(candidates, commandCandidate{Name: "py", Args: []string{"-3"}})
	}
	resolved := resolveCommand(candidates)
	if resolved.Path == "" {
		return ToolStatus{Name: "python", Found: false}
	}
	args := append([]string{}, resolved.Args...)
	args = append(args, "--version")
	version := strings.TrimSpace(runAndCapture("", resolved.Path, args...))
	status := ToolStatus{
		Name:    "python",
		Found:   true,
		Path:    resolved.Path,
		Version: version,
	}
	maj, min := parseMajorMinor(version)
	if maj == 0 && min == 0 {
		status.Note = "could not parse Python version"
		return status
	}
	if maj != 3 || min < supportedPythonMin[1] || min >= supportedPythonMaxExclusive[1] {
		status.Note = fmt.Sprintf("Studio release builds support Python >= %d.%d and < %d.%d", supportedPythonMin[0], supportedPythonMin[1], supportedPythonMaxExclusive[0], supportedPythonMaxExclusive[1])
	}
	return status
}

func resolveCommand(candidates []commandCandidate) resolvedCommand {
	for _, candidate := range candidates {
		if candidate.Name == "" {
			continue
		}
		path, err := exec.LookPath(candidate.Name)
		if err == nil {
			return resolvedCommand{Path: path, Args: candidate.Args}
		}
	}
	return resolvedCommand{}
}

func runAndCapture(dir, name string, args ...string) string {
	cmd := exec.Command(name, args...)
	if dir != "" {
		cmd.Dir = dir
	}
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	if err := cmd.Run(); err != nil {
		return ""
	}
	return out.String()
}

func parseMajorMinor(version string) (int, int) {
	version = strings.TrimSpace(version)
	version = strings.TrimPrefix(version, "Python ")
	version = strings.TrimPrefix(version, "go version go")
	version = strings.TrimPrefix(version, "v")
	var major, minor int
	if _, err := fmt.Sscanf(version, "%d.%d", &major, &minor); err != nil {
		return 0, 0
	}
	return major, minor
}

func executableOrBlank() string {
	path, err := os.Executable()
	if err != nil {
		return ""
	}
	return path
}

func npmCommandName() string {
	if runtime.GOOS == "windows" {
		return "npm.cmd"
	}
	return "npm"
}

func packagedAppName() string {
	if runtime.GOOS == "windows" {
		return "EDMG Studio.exe"
	}
	return "EDMG Studio"
}

func firstExisting(candidates ...string) string {
	for _, candidate := range candidates {
		if fileExists(candidate) {
			return candidate
		}
	}
	if len(candidates) == 0 {
		return ""
	}
	return candidates[0]
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func pathExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

func cleanPath(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	if resolved, err := filepath.Abs(value); err == nil {
		return resolved
	}
	return filepath.Clean(value)
}

func pathWithin(base, target string) bool {
	base = cleanPath(base)
	target = cleanPath(target)
	if base == "" || target == "" {
		return false
	}
	rel, err := filepath.Rel(base, target)
	if err != nil {
		return false
	}
	if rel == "." {
		return true
	}
	return !strings.HasPrefix(rel, "..") && rel != ".."
}
