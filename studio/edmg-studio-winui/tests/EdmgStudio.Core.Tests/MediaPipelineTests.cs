using EdmgStudio.Core.Graphics;
using EdmgStudio.Core.Media;

namespace EdmgStudio.Core.Tests;

[TestClass]
[DoNotParallelize]
public sealed class MediaPipelineTests
{
    [TestMethod]
    public void ResolvePrefersEnvironmentOverrides()
    {
        using var temporaryDirectory = new TemporaryDirectory();
        string ffmpegPath = temporaryDirectory.CreateFile("custom-ffmpeg.exe");
        string ffprobePath = temporaryDirectory.CreateFile("custom-ffprobe.exe");
        using var ffmpegEnvironment = new EnvironmentVariableScope("EDMG_FFMPEG_PATH", ffmpegPath);
        using var ffprobeEnvironment = new EnvironmentVariableScope("EDMG_FFPROBE_PATH", ffprobePath);

        MediaToolPaths paths = MediaToolLocator.Locate(temporaryDirectory.Path);

        Assert.AreEqual(ffmpegPath, paths.FfmpegPath);
        Assert.AreEqual(ffprobePath, paths.FfprobePath);
    }

    [TestMethod]
    public void ResolveFindsPackagedBinBeforeSearchRoots()
    {
        using var temporaryDirectory = new TemporaryDirectory();
        string applicationDirectory = System.IO.Path.Combine(temporaryDirectory.Path, "app");
        string packagedBin = System.IO.Path.Combine(applicationDirectory, "bin");
        Directory.CreateDirectory(packagedBin);
        string packagedFfmpeg = CreateFile(packagedBin, "ffmpeg.exe");
        string packagedFfprobe = CreateFile(packagedBin, "ffprobe.exe");
        using var ffmpegEnvironment = new EnvironmentVariableScope("EDMG_FFMPEG_PATH", null);
        using var ffprobeEnvironment = new EnvironmentVariableScope("EDMG_FFPROBE_PATH", null);

        MediaToolPaths paths = MediaToolLocator.Locate(applicationDirectory);

        Assert.AreEqual(packagedFfmpeg, paths.FfmpegPath);
        Assert.AreEqual(packagedFfprobe, paths.FfprobePath);
    }

    [TestMethod]
    public void ResolveInfersSiblingToolFromOneEnvironmentOverride()
    {
        using var temporaryDirectory = new TemporaryDirectory();
        string ffmpegPath = temporaryDirectory.CreateFile("ffmpeg.exe");
        string ffprobePath = temporaryDirectory.CreateFile("ffprobe.exe");
        using var ffmpegEnvironment = new EnvironmentVariableScope("EDMG_FFMPEG_PATH", ffmpegPath);
        using var ffprobeEnvironment = new EnvironmentVariableScope("EDMG_FFPROBE_PATH", null);

        MediaToolPaths paths = MediaToolLocator.Locate(temporaryDirectory.Path);

        Assert.AreEqual(ffmpegPath, paths.FfmpegPath);
        Assert.AreEqual(ffprobePath, paths.FfprobePath);
    }

    [TestMethod]
    public void ResolveFallsBackToCommandNames()
    {
        using var temporaryDirectory = new TemporaryDirectory();
        using var ffmpegEnvironment = new EnvironmentVariableScope("EDMG_FFMPEG_PATH", null);
        using var ffprobeEnvironment = new EnvironmentVariableScope("EDMG_FFPROBE_PATH", null);

        MediaToolPaths paths = MediaToolLocator.Locate(temporaryDirectory.Path);

        Assert.AreEqual("ffmpeg", paths.FfmpegPath);
        Assert.AreEqual("ffprobe", paths.FfprobePath);
    }

    [TestMethod]
    public void ParseFfprobeJsonReadsRotationDurationAndFrameRate()
    {
        const string json = """
            {
              "streams": [
                {
                  "codec_type": "audio"
                },
                {
                  "codec_type": "video",
                  "width": 1920,
                  "height": 1080,
                  "avg_frame_rate": "30000/1001",
                  "duration": "12.5",
                  "side_data_list": [
                    { "rotation": -90 }
                  ]
                }
              ],
              "format": {
                "duration": "99"
              }
            }
            """;

        VideoMetadata metadata = VideoMetadata.ParseFfprobeJson(json);

        Assert.AreEqual(1080, metadata.Width);
        Assert.AreEqual(1920, metadata.Height);
        Assert.AreEqual(TimeSpan.FromSeconds(12.5), metadata.Duration);
        Assert.AreEqual(30000d / 1001d, metadata.FramesPerSecond, 0.0001);
        Assert.AreEqual(270, metadata.RotationDegrees);
    }

    [TestMethod]
    public void ParseFfprobeJsonUsesFallbacks()
    {
        const string json = """
            {
              "streams": [
                {
                  "codec_type": "video",
                  "width": 640,
                  "height": 360,
                  "avg_frame_rate": "0/0",
                  "r_frame_rate": "invalid",
                  "tags": { "rotate": "91" }
                }
              ],
              "format": {
                "duration": 4.25
              }
            }
            """;

        VideoMetadata metadata = VideoMetadata.ParseFfprobeJson(json);

        Assert.AreEqual(360, metadata.Width);
        Assert.AreEqual(640, metadata.Height);
        Assert.AreEqual(TimeSpan.FromSeconds(4.25), metadata.Duration);
        Assert.AreEqual(VideoMetadata.DefaultFramesPerSecond, metadata.FramesPerSecond);
        Assert.AreEqual(90, metadata.RotationDegrees);
    }

    [TestMethod]
    public async Task ParseFfprobeJsonRejectsMissingVideoStream()
    {
        const string json = """{ "streams": [{ "codec_type": "audio" }] }""";

        InvalidDataException exception = await Assert.ThrowsExactlyAsync<InvalidDataException>(
            () => Task.Run(() => VideoMetadata.ParseFfprobeJson(json)));

        StringAssert.Contains(exception.Message, "video stream");
    }

    [TestMethod]
    public async Task ReadFrameAsyncReturnsFalseAtCleanEndOfStream()
    {
        await using var source = new MemoryStream();
        byte[] destination = new byte[4];

        bool hasFrame = await RawFrameReader.ReadFrameAsync(source, destination);

        Assert.IsFalse(hasFrame);
    }

    [TestMethod]
    public async Task ReadFrameAsyncAccumulatesPartialReads()
    {
        await using var source = new PartialReadStream([1, 2, 3, 4, 5], maximumReadSize: 2);
        byte[] destination = new byte[5];

        bool hasFrame = await RawFrameReader.ReadFrameAsync(source, destination);

        Assert.IsTrue(hasFrame);
        CollectionAssert.AreEqual(new byte[] { 1, 2, 3, 4, 5 }, destination);
    }

    [TestMethod]
    public async Task ReadFrameAsyncRejectsTruncatedFrame()
    {
        await using var source = new MemoryStream([1, 2, 3]);
        byte[] destination = new byte[4];

        EndOfStreamException exception = await Assert.ThrowsExactlyAsync<EndOfStreamException>(
            async () => await RawFrameReader.ReadFrameAsync(source, destination));

        StringAssert.Contains(exception.Message, "3 of 4");
    }

    [TestMethod]
    public async Task ReadFrameAsyncRejectsEmptyDestination()
    {
        await using var source = new MemoryStream();

        await Assert.ThrowsExactlyAsync<ArgumentException>(
            async () => await RawFrameReader.ReadFrameAsync(source, Memory<byte>.Empty));
    }

    [TestMethod]
    public async Task ReadFrameAsyncObservesCancellation()
    {
        await using var source = new MemoryStream([1]);
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();

        await Assert.ThrowsAsync<OperationCanceledException>(
            async () => await RawFrameReader.ReadFrameAsync(source, new byte[1], cancellation.Token));
    }

    [TestMethod]
    public async Task DecodeAsyncPreservesStartupFailure()
    {
        using var temporaryDirectory = new TemporaryDirectory();
        string missingExecutable = System.IO.Path.Combine(temporaryDirectory.Path, "missing.exe");
        var decoder = new FfmpegVideoDecoder(new MediaToolPaths(missingExecutable, missingExecutable));
        var metadata = new VideoMetadata(2, 2, TimeSpan.FromSeconds(1), 30, 0);

        InvalidOperationException exception = await Assert.ThrowsExactlyAsync<InvalidOperationException>(
            () => decoder.DecodeAsync(
                "missing.media",
                metadata,
                TimeSpan.Zero,
                static frame => frame.Dispose(),
                paceFrames: false,
                maximumFrames: 1,
                CancellationToken.None));

        StringAssert.Contains(exception.Message, "FFmpeg is unavailable");
    }

    [TestMethod]
    public async Task PlaybackCreationDeletesSpoolWhenProbeFails()
    {
        using var temporaryDirectory = new TemporaryDirectory();
        var decoder = new FakeVideoDecoder(new InvalidDataException("probe failed"));
        await using var source = new MemoryStream([1, 2, 3]);

        await Assert.ThrowsExactlyAsync<InvalidDataException>(
            () => VideoPlaybackSession.CreateAsync(source, decoder, temporaryDirectory.Path));

        Assert.IsEmpty(Directory.GetFiles(temporaryDirectory.Path));
    }

    [TestMethod]
    public async Task PlaybackReplacementCancelsPriorDecodeAndDisposalDeletesSpool()
    {
        using var temporaryDirectory = new TemporaryDirectory();
        var decoder = new FakeVideoDecoder();
        await using var source = new MemoryStream([1, 2, 3]);
        VideoPlaybackSession session = await VideoPlaybackSession.CreateAsync(
            source,
            decoder,
            temporaryDirectory.Path);
        string temporaryPath = session.TemporaryPath;
        Task firstDecode = session.DecodeAsync(
            TimeSpan.Zero,
            static frame => frame.Dispose(),
            paceFrames: false);
        await decoder.FirstDecodeStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));

        await session.DecodeAsync(
            TimeSpan.FromSeconds(1),
            static frame => frame.Dispose(),
            paceFrames: false,
            maximumFrames: 1);

        await Assert.ThrowsAsync<OperationCanceledException>(() => firstDecode);
        Assert.AreEqual(2, decoder.DecodeCount);
        Assert.AreEqual(TimeSpan.FromSeconds(1), decoder.LastStartPosition);
        Assert.IsTrue(File.Exists(temporaryPath));

        await session.DisposeAsync();

        Assert.IsFalse(File.Exists(temporaryPath));
    }

    private static string CreateFile(string directory, string fileName)
    {
        string path = System.IO.Path.Combine(directory, fileName);
        File.WriteAllBytes(path, []);
        return System.IO.Path.GetFullPath(path);
    }

    private sealed class FakeVideoDecoder(Exception? probeError = null) : IVideoDecoder
    {
        private int decodeCount;

        public TaskCompletionSource FirstDecodeStarted { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        public int DecodeCount => Volatile.Read(ref decodeCount);

        public TimeSpan LastStartPosition { get; private set; }

        public Task<VideoMetadata> ProbeAsync(string sourcePath, CancellationToken cancellationToken = default)
        {
            if (probeError is not null)
            {
                return Task.FromException<VideoMetadata>(probeError);
            }

            return Task.FromResult(new VideoMetadata(2, 2, TimeSpan.FromSeconds(3), 30, 0));
        }

        public async Task DecodeAsync(
            string sourcePath,
            VideoMetadata metadata,
            TimeSpan startPosition,
            Action<OwnedCpuFrame> submitFrame,
            bool paceFrames = true,
            int? maximumFrames = null,
            CancellationToken cancellationToken = default)
        {
            int call = Interlocked.Increment(ref decodeCount);
            LastStartPosition = startPosition;
            if (call == 1)
            {
                FirstDecodeStarted.TrySetResult();
                await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
            }
        }
    }

    private sealed class PartialReadStream(byte[] bytes, int maximumReadSize) : MemoryStream(bytes)
    {
        public override ValueTask<int> ReadAsync(
            Memory<byte> buffer,
            CancellationToken cancellationToken = default)
            => base.ReadAsync(buffer[..Math.Min(buffer.Length, maximumReadSize)], cancellationToken);
    }

    private sealed class EnvironmentVariableScope : IDisposable
    {
        private readonly string name;
        private readonly string? previousValue;

        public EnvironmentVariableScope(string name, string? value)
        {
            this.name = name;
            previousValue = Environment.GetEnvironmentVariable(name);
            Environment.SetEnvironmentVariable(name, value);
        }

        public void Dispose() => Environment.SetEnvironmentVariable(name, previousValue);
    }

    private sealed class TemporaryDirectory : IDisposable
    {
        public TemporaryDirectory()
        {
            Path = System.IO.Path.Combine(
                System.IO.Path.GetTempPath(),
                $"edmg-media-tests-{Guid.NewGuid():N}");
            Directory.CreateDirectory(Path);
        }

        public string Path { get; }

        public string CreateFile(string fileName) => MediaPipelineTests.CreateFile(Path, fileName);

        public void Dispose()
        {
            try
            {
                Directory.Delete(Path, recursive: true);
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }
    }
}
