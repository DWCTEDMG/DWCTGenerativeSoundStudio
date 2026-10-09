using EdmgStudio.Core.Audio;
using EdmgStudio.WinUI.Services;

namespace EdmgStudio.Core.Tests;

[TestClass]
public sealed class AudioPreviewEngineSelectionTests
{
  [TestMethod]
  public void WindowsPreferenceStoreIsSafeForUnpackagedSourceRuns()
  {
    if (WindowsPackageIdentity.IsPackaged)
    {
      Assert.Inconclusive("This regression test exercises the unpackaged source-build boundary.");
    }

    string directory = Path.Combine(Path.GetTempPath(), "EDMG-audio-test-" + Guid.NewGuid());
    string path = Path.Combine(directory, "audio.json");
    try
    {
      WindowsAudioPreviewEnginePreferenceStore store = new(path);
      Assert.AreEqual(AudioPreviewEngine.AudioGraph, store.Load());
      WindowsAudioPreviewEnginePreferenceStore.WritePreferences(new(DeviceId: "device-1", BufferFrames: 256), path);
      store.Save(AudioPreviewEngine.Juce);
      Assert.AreEqual(AudioPreviewEngine.Juce, new WindowsAudioPreviewEnginePreferenceStore(path).Load());
      var saved = WindowsAudioPreviewEnginePreferenceStore.ReadPreferences(path);
      Assert.AreEqual("device-1", saved.DeviceId);
      Assert.AreEqual(256, saved.BufferFrames);
      File.WriteAllText(path, "invalid json");
      Assert.AreEqual(AudioPreviewEngine.AudioGraph, store.Load());
    }
    finally
    {
      if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
    }
  }

  [TestMethod]
  public void DefaultsToAudioGraphAndPersistsStoppedSelection()
  {
    MemoryStore store = new(AudioPreviewEngine.AudioGraph);
    AudioPreviewEngineSelection selection = new(store, () => true);

    AudioPreviewEngineSelectionResult result = selection.Select(AudioPreviewEngine.Juce, TransportMode.Stopped);

    Assert.IsTrue(result.Changed);
    Assert.AreEqual(AudioPreviewEngine.Juce, selection.SelectedEngine);
    Assert.AreEqual(AudioPreviewEngine.Juce, store.Saved);
  }

  [TestMethod]
  public void RejectsSwitchWhileTransportIsActive()
  {
    MemoryStore store = new(AudioPreviewEngine.AudioGraph);
    AudioPreviewEngineSelection selection = new(store, () => true);

    AudioPreviewEngineSelectionResult result = selection.Select(AudioPreviewEngine.Juce, TransportMode.Playing);

    Assert.IsFalse(result.Changed);
    Assert.AreEqual(AudioPreviewEngine.AudioGraph, result.SelectedEngine);
    Assert.AreEqual(AudioPreviewEngine.AudioGraph, store.Saved);
  }

  [TestMethod]
  public void MissingJuceHostFallsBackWithoutChangingProjectState()
  {
    MemoryStore store = new(AudioPreviewEngine.Juce);

    AudioPreviewEngineSelection selection = new(store, () => false);
    AudioPreviewEngineSelectionResult result = selection.Select(AudioPreviewEngine.Juce, TransportMode.Stopped);

    Assert.AreEqual(AudioPreviewEngine.AudioGraph, selection.SelectedEngine);
    Assert.AreEqual(AudioPreviewEngine.AudioGraph, store.Saved);
    Assert.IsFalse(result.Changed);
    StringAssert.Contains(result.Message, "not installed");
  }

  [TestMethod]
  public void AudioGraphRollbackRemainsAvailableWhenJuceHostDisappears()
  {
    MemoryStore store = new(AudioPreviewEngine.Juce);
    AudioPreviewEngineSelection selection = new(store, () => true);

    AudioPreviewEngineSelectionResult result = selection.Select(AudioPreviewEngine.AudioGraph, TransportMode.Stopped);

    Assert.IsTrue(result.Changed);
    Assert.AreEqual(AudioPreviewEngine.AudioGraph, result.SelectedEngine);
    Assert.AreEqual(AudioPreviewEngine.AudioGraph, store.Saved);
  }

  private sealed class MemoryStore(AudioPreviewEngine initial) : IAudioPreviewEnginePreferenceStore
  {
    public AudioPreviewEngine Saved { get; private set; } = initial;

    public AudioPreviewEngine Load() => Saved;

    public void Save(AudioPreviewEngine engine) => Saved = engine;
  }
}
