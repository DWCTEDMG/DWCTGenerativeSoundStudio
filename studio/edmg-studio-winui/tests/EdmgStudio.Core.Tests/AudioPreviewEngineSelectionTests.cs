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

    WindowsAudioPreviewEnginePreferenceStore store = new();

    Assert.AreEqual(AudioPreviewEngine.AudioGraph, store.Load());
    store.Save(AudioPreviewEngine.Juce);
    Assert.AreEqual(AudioPreviewEngine.AudioGraph, store.Load());
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
