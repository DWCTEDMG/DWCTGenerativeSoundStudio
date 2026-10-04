#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_core/juce_core.h>
#include <atomic>
#include <cmath>
#include <iostream>
#include <memory>
#include <vector>

namespace
{
constexpr int protocolVersion = 1;
constexpr int maximumMessageBytes = 1024 * 1024;
constexpr int maximumPreparedSources = 256;
constexpr int maximumPreparedTracks = 512;
constexpr int maximumPreparedClips = 8192;
constexpr int maximumPreparedSamples = 262144;

juce::var makeHandshake(const bool compatible, const juce::String& diagnostic)
{
	auto* object = new juce::DynamicObject();
	object->setProperty("protocolVersion", protocolVersion);
	object->setProperty("hostBuildIdentity", "edmg-juce-audio-host/0.2.0");
#if JUCE_64BIT
	object->setProperty("architecture", "x64");
#else
	object->setProperty("architecture", "unsupported");
#endif
	juce::Array<juce::var> features;
	features.add("lifecycle");
	features.add("device_enumeration");
	features.add("generated_tone_transport");
	features.add("prepared_timeline_v1");
	features.add("file_backed_prepared_media_v1");
	object->setProperty("featureFlags", features);
	object->setProperty("engineState", "ready_without_device");
	object->setProperty("compatible", compatible);
	object->setProperty("diagnostic", diagnostic);
	return juce::var(object);
}

bool validHandshake(const juce::var& value, const juce::String& expectedToken)
{
	auto* object = value.getDynamicObject();
	if (object == nullptr || !object->hasProperty("minimumProtocolVersion")
		|| !object->hasProperty("maximumProtocolVersion") || !object->hasProperty("clientBuildIdentity")
		|| !object->hasProperty("sessionToken"))
		return false;

	const auto minimum = static_cast<int>(object->getProperty("minimumProtocolVersion"));
	const auto maximum = static_cast<int>(object->getProperty("maximumProtocolVersion"));
	const auto clientBuildIdentity = object->getProperty("clientBuildIdentity").toString();
	const auto token = object->getProperty("sessionToken").toString();
	return minimum > 0 && minimum <= maximum && minimum <= protocolVersion && maximum >= protocolVersion
		&& clientBuildIdentity.isNotEmpty() && clientBuildIdentity.length() <= 256
		&& token.length() == 64 && token == expectedToken;
}

struct PreparedSource
{
	juce::String id;
	int sampleRate = 0;
	int channels = 0;
	std::vector<float> samples;
	std::unique_ptr<juce::MemoryMappedAudioFormatReader> mappedReader;

	juce::int64 frameCount() const noexcept
	{
		return mappedReader != nullptr ? mappedReader->lengthInSamples
			: static_cast<juce::int64>(samples.size() / static_cast<std::size_t>(channels));
	}
};

struct PreparedClip
{
	juce::String eventId;
	juce::int64 timelineStart = 0;
	juce::int64 timelineEnd = 0;
	juce::int64 sourceStart = 0;
	double playbackRate = 1.0;
	juce::int64 fadeIn = 0;
	juce::int64 fadeOut = 0;
	int fadeCurve = 0;
	const PreparedSource* source = nullptr;
};

struct PreparedTrack
{
	juce::String id;
	float leftGain = 1.0f;
	float rightGain = 1.0f;
	std::vector<PreparedClip> clips;
};

struct PreparedTimelineSnapshot
{
	juce::int64 revision = 0;
	int sampleRate = 0;
	juce::int64 duration = 0;
	std::vector<PreparedSource> sources;
	std::vector<PreparedTrack> tracks;
};

float fadeGain(const PreparedClip& clip, const juce::int64 relative) noexcept
{
	auto curve = [&clip](double value)
	{
		value = juce::jlimit(0.0, 1.0, value);
		if (clip.fadeCurve == 0) return value;
		if (clip.fadeCurve == 1) return std::sin(value * juce::MathConstants<double>::halfPi);
		return value * value * (3.0 - (2.0 * value));
	};
	double gain = 1.0;
	if (clip.fadeIn > 0 && relative < clip.fadeIn)
		gain = curve(static_cast<double>(relative) / static_cast<double>(clip.fadeIn));
	const auto remaining = clip.timelineEnd - clip.timelineStart - relative - 1;
	if (clip.fadeOut > 0 && remaining < clip.fadeOut)
		gain = juce::jmin(gain, curve(static_cast<double>(remaining) / static_cast<double>(clip.fadeOut)));
	return static_cast<float>(gain);
}

void readLinear(const PreparedSource& source, const double sourceFrame, float& left, float& right) noexcept
{
	const auto first = static_cast<juce::int64>(std::floor(sourceFrame));
	if (first < 0 || first >= source.frameCount())
	{
		left = right = 0.0f;
		return;
	}
	const auto second = juce::jmin(first + 1, source.frameCount() - 1);
	const auto amount = static_cast<float>(sourceFrame - static_cast<double>(first));
	if (source.mappedReader != nullptr)
	{
		float firstValues[2]{};
		float secondValues[2]{};
		source.mappedReader->getSample(first, firstValues);
		source.mappedReader->getSample(second, secondValues);
		left = firstValues[0] + ((secondValues[0] - firstValues[0]) * amount);
		right = source.channels == 1 ? left
			: firstValues[1] + ((secondValues[1] - firstValues[1]) * amount);
		return;
	}
	const auto firstOffset = static_cast<std::size_t>(first * source.channels);
	const auto secondOffset = static_cast<std::size_t>(second * source.channels);
	left = source.samples[firstOffset] + ((source.samples[secondOffset] - source.samples[firstOffset]) * amount);
	right = source.channels == 1 ? left : source.samples[firstOffset + 1]
		+ ((source.samples[secondOffset + 1] - source.samples[firstOffset + 1]) * amount);
}

void renderTimelineSample(const PreparedTimelineSnapshot& snapshot, const juce::int64 timelineSample,
	float& mixedLeft, float& mixedRight) noexcept
{
	mixedLeft = mixedRight = 0.0f;
	for (const auto& track : snapshot.tracks)
	{
		for (const auto& clip : track.clips)
		{
			if (timelineSample < clip.timelineStart || timelineSample >= clip.timelineEnd)
				continue;
			const auto relative = timelineSample - clip.timelineStart;
			const auto sourceFrame = static_cast<double>(clip.sourceStart)
				+ (static_cast<double>(relative) * static_cast<double>(clip.source->sampleRate)
					/ static_cast<double>(snapshot.sampleRate) * clip.playbackRate);
			float left = 0.0f;
			float right = 0.0f;
			readLinear(*clip.source, sourceFrame, left, right);
			const auto fade = fadeGain(clip, relative);
			mixedLeft += left * fade * track.leftGain;
			mixedRight += right * fade * track.rightGain;
		}
	}
}

class GeneratedToneCallback final : public juce::AudioIODeviceCallback
{
public:
	void configure(const juce::int64 newRevision, const int newSampleRate,
		const juce::int64 newDuration, const double newFrequency)
	{
		projectRevision.store(newRevision);
		sampleRate.store(newSampleRate);
		duration.store(newDuration);
		frequency.store(newFrequency);
		position.store(0);
		seekSequence.store(0);
		loopStart.store(0);
		loopEnd.store(newDuration);
		loopEnabled.store(false);
		pendingSnapshot.store(nullptr, std::memory_order_release);
		playing.store(false);
	}

	void publish(const PreparedTimelineSnapshot* snapshot) noexcept
	{
		pendingSnapshot.store(snapshot, std::memory_order_release);
	}

	void audioDeviceIOCallbackWithContext(const float* const*, int, float* const* outputs,
		const int outputChannels, const int frames, const juce::AudioIODeviceCallbackContext&) override
	{
		for (int channel = 0; channel < outputChannels; ++channel)
			juce::FloatVectorOperations::clear(outputs[channel], frames);
		if (const auto* published = pendingSnapshot.load(std::memory_order_acquire); published != activeSnapshot)
		{
			previousSnapshot = activeSnapshot;
			activeSnapshot = published;
			transitionSamplesRemaining = previousSnapshot == nullptr ? 0 : snapshotTransitionSamples;
		}
		if (!playing.load())
			return;

		auto current = position.load();
		const auto end = duration.load();
		const auto shouldLoop = loopEnabled.load();
		const auto firstLoopSample = loopStart.load();
		const auto afterLoopSample = loopEnd.load();
		for (int frame = 0; frame < frames && current < end; ++frame)
		{
			float mixedLeft = 0.0f;
			float mixedRight = 0.0f;
			if (activeSnapshot != nullptr)
				renderTimelineSample(*activeSnapshot, current, mixedLeft, mixedRight);
			else
			{
				const auto value = static_cast<float>(0.1 * std::sin(juce::MathConstants<double>::twoPi
					* frequency.load() * static_cast<double>(current) / sampleRate.load()));
				mixedLeft = mixedRight = value;
			}
			if (transitionSamplesRemaining > 0 && previousSnapshot != nullptr)
			{
				float previousLeft = 0.0f;
				float previousRight = 0.0f;
				renderTimelineSample(*previousSnapshot, current, previousLeft, previousRight);
				const auto newAmount = 1.0f - (static_cast<float>(transitionSamplesRemaining)
					/ static_cast<float>(snapshotTransitionSamples));
				mixedLeft = previousLeft + ((mixedLeft - previousLeft) * newAmount);
				mixedRight = previousRight + ((mixedRight - previousRight) * newAmount);
				if (--transitionSamplesRemaining == 0)
					previousSnapshot = nullptr;
			}
			if (outputChannels > 0) outputs[0][frame] = mixedLeft;
			if (outputChannels > 1) outputs[1][frame] = mixedRight;
			++current;
			if (shouldLoop && current >= afterLoopSample)
				current = firstLoopSample;
		}
		position.store(current);
		if (!shouldLoop && current >= end)
			playing.store(false);
	}

	void audioDeviceAboutToStart(juce::AudioIODevice*) override {}
	void audioDeviceStopped() override { playing.store(false); }
	void audioDeviceError(const juce::String&) override { deviceError.store(true); playing.store(false); }

	std::atomic<juce::int64> projectRevision { 0 };
	std::atomic<int> sampleRate { 48000 };
	std::atomic<juce::int64> duration { 0 };
	std::atomic<juce::int64> position { 0 };
	std::atomic<juce::int64> loopStart { 0 };
	std::atomic<juce::int64> loopEnd { 0 };
	std::atomic<juce::int64> seekSequence { 0 };
	std::atomic<double> frequency { 440.0 };
	std::atomic<bool> playing { false };
	std::atomic<bool> loopEnabled { false };
	std::atomic<bool> deviceError { false };
	std::atomic<const PreparedTimelineSnapshot*> pendingSnapshot { nullptr };
	static constexpr int snapshotTransitionSamples = 128;
	const PreparedTimelineSnapshot* activeSnapshot = nullptr;
	const PreparedTimelineSnapshot* previousSnapshot = nullptr;
	int transitionSamplesRemaining = 0;
};

juce::var makeEnvelope(const juce::int64 sequence, const juce::String& correlation,
	const juce::String& kind, const juce::var& payload)
{
	auto* object = new juce::DynamicObject();
	object->setProperty("protocolVersion", protocolVersion);
	object->setProperty("sequence", sequence);
	object->setProperty("correlationId", correlation);
	object->setProperty("kind", kind);
	object->setProperty("payload", payload);
	return juce::var(object);
}

void writeEnvelope(juce::int64& sequence, const juce::String& correlation,
	const juce::String& kind, const juce::var& payload)
{
	std::cout << juce::JSON::toString(makeEnvelope(++sequence, correlation, kind, payload), true).toStdString() << std::endl;
}

juce::var makeError(const juce::String& code, const juce::String& message)
{
	auto* error = new juce::DynamicObject();
	error->setProperty("code", code);
	error->setProperty("message", message);
	return juce::var(error);
}

juce::var makePosition(const GeneratedToneCallback& tone)
{
	auto* result = new juce::DynamicObject();
	result->setProperty("projectRevision", tone.projectRevision.load());
	result->setProperty("positionSamples", tone.position.load());
	result->setProperty("sampleRate", tone.sampleRate.load());
	result->setProperty("state", tone.playing.load() ? "playing" : "stopped");
	result->setProperty("loopEnabled", tone.loopEnabled.load());
	result->setProperty("loopStartSample", tone.loopStart.load());
	result->setProperty("loopEndSample", tone.loopEnd.load());
	result->setProperty("seekSequence", tone.seekSequence.load());
	return juce::var(result);
}
}

int main()
{
	juce::ConsoleApplication application;
	const auto expectedToken = juce::SystemStats::getEnvironmentVariable("EDMG_JUCE_SESSION_TOKEN", {});
	std::string line;
	if (expectedToken.isEmpty() || !std::getline(std::cin, line)
		|| line.size() > static_cast<std::size_t>(maximumMessageBytes))
		return 2;

	const auto request = juce::JSON::parse(juce::String::fromUTF8(line.data(), static_cast<int>(line.size())));
	const bool compatible = validHandshake(request, expectedToken);
	std::cout << juce::JSON::toString(makeHandshake(compatible,
		compatible ? juce::String{} : "Authentication or protocol negotiation failed."), true).toStdString() << std::endl;
	if (!compatible)
		return 3;

	juce::AudioDeviceManager deviceManager;
	GeneratedToneCallback tone;
	std::vector<std::unique_ptr<PreparedTimelineSnapshot>> timelineSnapshots;
	bool callbackAttached = false;
	juce::int64 eventSequence = 0;
	while (std::getline(std::cin, line))
	{
		if (line.size() > static_cast<std::size_t>(maximumMessageBytes))
			return 4;
		const auto message = juce::JSON::parse(juce::String::fromUTF8(line.data(), static_cast<int>(line.size())));
		auto* envelope = message.getDynamicObject();
		if (envelope == nullptr || !envelope->hasProperty("protocolVersion") || !envelope->hasProperty("sequence")
			|| !envelope->hasProperty("correlationId") || !envelope->hasProperty("kind") || !envelope->hasProperty("payload")
			|| static_cast<int>(envelope->getProperty("protocolVersion")) != protocolVersion
			|| static_cast<juce::int64>(envelope->getProperty("sequence")) <= 0)
			return 5;
		auto* payload = envelope->getProperty("payload").getDynamicObject();
		const auto correlation = envelope->getProperty("correlationId").toString();
		const auto kind = envelope->getProperty("kind").toString();
		if (correlation.isEmpty() || kind.isEmpty())
			return 5;
		if (kind == "list_devices")
		{
			juce::Array<juce::var> devices;
			for (auto* type : deviceManager.getAvailableDeviceTypes())
			{
				type->scanForDevices();
				const auto names = type->getDeviceNames(false);
				for (int index = 0; index < names.size(); ++index)
				{
					auto* device = new juce::DynamicObject();
					device->setProperty("id", type->getTypeName() + ":" + names[index]);
					device->setProperty("name", names[index]);
					device->setProperty("api", type->getTypeName());
					device->setProperty("inputChannels", 0);
					device->setProperty("outputChannels", 2);
					device->setProperty("sampleRates", juce::Array<juce::var>{ 44100, 48000, 96000 });
					device->setProperty("bufferSizes", juce::Array<juce::var>{ 128, 256, 512, 1024 });
					device->setProperty("supportsSharedMode", true);
					device->setProperty("supportsExclusiveMode", false);
					device->setProperty("isDefaultOutput", index == type->getDefaultDeviceIndex(false));
					devices.add(juce::var(device));
				}
			}
			writeEnvelope(eventSequence, correlation, "device_list", devices);
		}
		else if (kind == "configure_device" && payload != nullptr)
		{
			const auto deviceId = payload->getProperty("deviceId").toString();
			const auto rate = static_cast<int>(payload->getProperty("sampleRate"));
			const auto buffer = static_cast<int>(payload->getProperty("bufferFrames"));
			const auto channels = static_cast<int>(payload->getProperty("outputChannels"));
			if (deviceId.isEmpty() || rate <= 0 || buffer <= 0 || channels <= 0 || channels > 2
				|| static_cast<bool>(payload->getProperty("exclusiveMode")))
			{
				writeEnvelope(eventSequence, correlation, "error",
					makeError("JUCE_INVALID_DEVICE_CONFIGURATION", "Device configuration is invalid or requests unsupported exclusive mode."));
				continue;
			}
			juce::AudioDeviceManager::AudioDeviceSetup setup;
			deviceManager.getAudioDeviceSetup(setup);
			setup.outputDeviceName = deviceId.fromFirstOccurrenceOf(":", false, false);
			setup.sampleRate = rate;
			setup.bufferSize = buffer;
			const auto error = deviceManager.initialise(0, channels, nullptr, false);
			const auto setupError = error.isEmpty() ? deviceManager.setAudioDeviceSetup(setup, true) : error;
			if (setupError.isNotEmpty())
			{
				writeEnvelope(eventSequence, correlation, "error", makeError("JUCE_DEVICE_OPEN_FAILED", setupError));
				continue;
			}
			if (!callbackAttached)
			{
				deviceManager.addAudioCallback(&tone);
				callbackAttached = true;
			}
			auto* result = new juce::DynamicObject();
			result->setProperty("configured", true);
			result->setProperty("diagnostic", juce::var());
			result->setProperty("deviceId", deviceId);
			result->setProperty("sampleRate", static_cast<int>(deviceManager.getCurrentAudioDevice()->getCurrentSampleRate()));
			result->setProperty("bufferFrames", deviceManager.getCurrentAudioDevice()->getCurrentBufferSizeSamples());
			result->setProperty("outputChannels", channels);
			writeEnvelope(eventSequence, correlation, "device_configured", juce::var(result));
		}
		else if (kind == "close_device")
		{
			tone.playing.store(false);
			if (callbackAttached)
			{
				deviceManager.removeAudioCallback(&tone);
				callbackAttached = false;
			}
			deviceManager.closeAudioDevice();
			auto* result = new juce::DynamicObject();
			result->setProperty("configured", false);
			result->setProperty("diagnostic", juce::var());
			writeEnvelope(eventSequence, correlation, "device_closed", juce::var(result));
		}
		else if (kind == "configure_transport" && payload != nullptr)
		{
			const auto revision = static_cast<juce::int64>(payload->getProperty("projectRevision"));
			const auto rate = static_cast<int>(payload->getProperty("sampleRate"));
			const auto samples = static_cast<juce::int64>(payload->getProperty("durationSamples"));
			const auto frequency = static_cast<double>(payload->getProperty("toneFrequencyHz"));
			if (revision < 0 || rate <= 0 || samples < 0 || !std::isfinite(frequency) || frequency <= 0 || frequency >= rate / 2.0)
			{
				writeEnvelope(eventSequence, correlation, "error",
					makeError("JUCE_INVALID_TRANSPORT_CONFIGURATION", "Generated transport configuration is invalid."));
				continue;
			}
			tone.configure(revision, rate, samples, frequency);
			writeEnvelope(eventSequence, correlation, "transport_configured", makePosition(tone));
		}
		else if (kind == "prepare_timeline" && payload != nullptr)
		{
			auto snapshot = std::make_unique<PreparedTimelineSnapshot>();
			snapshot->revision = static_cast<juce::int64>(payload->getProperty("revision"));
			snapshot->sampleRate = static_cast<int>(payload->getProperty("sampleRate"));
			snapshot->duration = static_cast<juce::int64>(payload->getProperty("durationSamples"));
			auto* sourceValues = payload->getProperty("sources").getArray();
			auto* trackValues = payload->getProperty("tracks").getArray();
			bool valid = snapshot->revision >= 0 && snapshot->sampleRate > 0 && snapshot->duration >= 0
				&& sourceValues != nullptr && trackValues != nullptr
				&& sourceValues->size() <= maximumPreparedSources && trackValues->size() <= maximumPreparedTracks
				&& (timelineSnapshots.empty() || snapshot->revision > timelineSnapshots.back()->revision);
			juce::StringArray sourceIds;
			juce::StringArray trackIds;
			juce::StringArray eventIds;
			int totalSamples = 0;
			if (valid)
			{
				snapshot->sources.reserve(static_cast<std::size_t>(sourceValues->size()));
				for (const auto& sourceValue : *sourceValues)
				{
					auto* sourceObject = sourceValue.getDynamicObject();
					auto* samples = sourceObject == nullptr ? nullptr : sourceObject->getProperty("interleavedSamples").getArray();
					PreparedSource source;
					juce::String authorizedPath;
					juce::int64 declaredFrameCount = 0;
					if (sourceObject != nullptr)
					{
						source.id = sourceObject->getProperty("sourceId").toString();
						source.sampleRate = static_cast<int>(sourceObject->getProperty("sampleRate"));
						source.channels = static_cast<int>(sourceObject->getProperty("channels"));
						authorizedPath = sourceObject->getProperty("authorizedPath").toString();
						declaredFrameCount = static_cast<juce::int64>(sourceObject->getProperty("frameCount"));
					}
					const bool fileBacked = authorizedPath.isNotEmpty();
					valid = sourceObject != nullptr && samples != nullptr && source.id.isNotEmpty()
						&& !sourceIds.contains(source.id)
						&& source.sampleRate > 0 && source.channels >= 1 && source.channels <= 2;
					if (!valid) break;
					sourceIds.add(source.id);
					if (fileBacked)
					{
						const juce::File mediaFile(authorizedPath);
						const auto extension = mediaFile.getFileExtension().toLowerCase();
						if (!juce::File::isAbsolutePath(authorizedPath) || !mediaFile.existsAsFile()
							|| (extension != ".wav" && extension != ".wave" && extension != ".aif" && extension != ".aiff"))
						{
							valid = false;
							break;
						}
						if (extension == ".wav" || extension == ".wave")
						{
							juce::WavAudioFormat format;
							source.mappedReader.reset(format.createMemoryMappedReader(mediaFile));
						}
						else
						{
							juce::AiffAudioFormat format;
							source.mappedReader.reset(format.createMemoryMappedReader(mediaFile));
						}
						valid = source.mappedReader != nullptr && source.mappedReader->mapEntireFile()
							&& static_cast<int>(std::llround(source.mappedReader->sampleRate)) == source.sampleRate
							&& static_cast<int>(source.mappedReader->numChannels) == source.channels
							&& declaredFrameCount > 0 && source.mappedReader->lengthInSamples == declaredFrameCount;
						if (valid)
						{
							for (juce::int64 frame = 0; frame < source.mappedReader->lengthInSamples; frame += 4096)
								source.mappedReader->touchSample(frame);
							source.mappedReader->touchSample(source.mappedReader->lengthInSamples - 1);
						}
					}
					else
					{
						valid = samples->size() > 0 && samples->size() % source.channels == 0
							&& samples->size() <= maximumPreparedSamples - totalSamples;
						if (!valid) break;
						totalSamples += samples->size();
						source.samples.reserve(static_cast<std::size_t>(samples->size()));
						for (const auto& sampleValue : *samples)
						{
							const auto sample = static_cast<double>(sampleValue);
							if (!std::isfinite(sample)) { valid = false; break; }
							source.samples.push_back(static_cast<float>(sample));
						}
					}
					if (!valid) break;
					snapshot->sources.push_back(std::move(source));
				}
			}
			int clipCount = 0;
			if (valid)
			{
				snapshot->tracks.reserve(static_cast<std::size_t>(trackValues->size()));
				for (const auto& trackValue : *trackValues)
				{
					auto* trackObject = trackValue.getDynamicObject();
					auto* clips = trackObject == nullptr ? nullptr : trackObject->getProperty("clips").getArray();
					PreparedTrack track;
					if (trackObject != nullptr)
					{
						track.id = trackObject->getProperty("trackId").toString();
						track.leftGain = static_cast<float>(static_cast<double>(trackObject->getProperty("leftGain")));
						track.rightGain = static_cast<float>(static_cast<double>(trackObject->getProperty("rightGain")));
					}
					valid = trackObject != nullptr && clips != nullptr && track.id.isNotEmpty()
						&& !trackIds.contains(track.id) && clips->size() <= maximumPreparedClips - clipCount
						&& std::isfinite(track.leftGain) && std::isfinite(track.rightGain);
					if (!valid) break;
					trackIds.add(track.id);
					track.clips.reserve(static_cast<std::size_t>(clips->size()));
					for (const auto& clipValue : *clips)
					{
						auto* clipObject = clipValue.getDynamicObject();
						if (clipObject == nullptr) { valid = false; break; }
						PreparedClip clip;
						clip.eventId = clipObject->getProperty("eventId").toString();
						clip.timelineStart = static_cast<juce::int64>(clipObject->getProperty("timelineStartSample"));
						clip.timelineEnd = static_cast<juce::int64>(clipObject->getProperty("timelineEndSample"));
						clip.sourceStart = static_cast<juce::int64>(clipObject->getProperty("sourceStartSample"));
						clip.playbackRate = static_cast<double>(clipObject->getProperty("playbackRate"));
						clip.fadeIn = static_cast<juce::int64>(clipObject->getProperty("fadeInSamples"));
						clip.fadeOut = static_cast<juce::int64>(clipObject->getProperty("fadeOutSamples"));
						const auto curve = clipObject->getProperty("fadeCurve").toString();
						clip.fadeCurve = curve == "linear" ? 0 : curve == "equal_power" ? 1 : curve == "s_curve" ? 2 : -1;
						const auto sourceId = clipObject->getProperty("sourceId").toString();
						for (const auto& source : snapshot->sources)
							if (source.id == sourceId) { clip.source = &source; break; }
						const auto duration = clip.timelineEnd - clip.timelineStart;
						const auto sourceLast = static_cast<double>(clip.sourceStart)
							+ (static_cast<double>(duration - 1) * static_cast<double>(clip.source == nullptr ? 0 : clip.source->sampleRate)
								/ static_cast<double>(snapshot->sampleRate) * clip.playbackRate);
						valid = clip.eventId.isNotEmpty() && !eventIds.contains(clip.eventId)
							&& clip.timelineStart >= 0 && clip.timelineEnd > clip.timelineStart
							&& clip.timelineEnd <= snapshot->duration && clip.sourceStart >= 0 && clip.source != nullptr
							&& std::isfinite(clip.playbackRate) && clip.playbackRate >= 0.25 && clip.playbackRate <= 4.0
							&& clip.fadeIn >= 0 && clip.fadeOut >= 0 && clip.fadeIn <= duration - clip.fadeOut
							&& clip.fadeCurve >= 0 && std::isfinite(sourceLast) && std::floor(sourceLast) < clip.source->frameCount();
						if (!valid) break;
						eventIds.add(clip.eventId);
						track.clips.push_back(clip);
						++clipCount;
					}
					if (!valid) break;
					snapshot->tracks.push_back(std::move(track));
				}
			}
			if (!valid)
			{
				writeEnvelope(eventSequence, correlation, "error",
					makeError("JUCE_INVALID_TIMELINE_SNAPSHOT", "Prepared Timeline snapshot is invalid or stale."));
				continue;
			}
			tone.projectRevision.store(snapshot->revision);
			tone.sampleRate.store(snapshot->sampleRate);
			tone.duration.store(snapshot->duration);
			tone.position.store(0);
			tone.seekSequence.store(0);
			tone.loopStart.store(0);
			tone.loopEnd.store(snapshot->duration);
			tone.loopEnabled.store(false);
			tone.playing.store(false);
			timelineSnapshots.push_back(std::move(snapshot));
			tone.publish(timelineSnapshots.back().get());
			auto* result = new juce::DynamicObject();
			result->setProperty("prepared", true);
			result->setProperty("revision", timelineSnapshots.back()->revision);
			result->setProperty("sampleRate", timelineSnapshots.back()->sampleRate);
			result->setProperty("durationSamples", timelineSnapshots.back()->duration);
			result->setProperty("sourceCount", static_cast<int>(timelineSnapshots.back()->sources.size()));
			result->setProperty("trackCount", static_cast<int>(timelineSnapshots.back()->tracks.size()));
			result->setProperty("clipCount", clipCount);
			writeEnvelope(eventSequence, correlation, "timeline_prepared", juce::var(result));
		}
		else if (kind == "render_timeline" && payload != nullptr)
		{
			const auto start = static_cast<juce::int64>(payload->getProperty("startSample"));
			const auto frames = static_cast<int>(payload->getProperty("frames"));
			if (timelineSnapshots.empty() || start < 0 || frames < 0 || frames > 4096
				|| start > timelineSnapshots.back()->duration || frames > timelineSnapshots.back()->duration - start)
			{
				writeEnvelope(eventSequence, correlation, "error",
					makeError("JUCE_INVALID_RENDER_REQUEST", "Deterministic Timeline render request is invalid."));
				continue;
			}
			juce::Array<juce::var> samples;
			for (int frame = 0; frame < frames; ++frame)
			{
				float left = 0.0f;
				float right = 0.0f;
				renderTimelineSample(*timelineSnapshots.back(), start + frame, left, right);
				samples.add(left);
				samples.add(right);
			}
			auto* result = new juce::DynamicObject();
			result->setProperty("revision", timelineSnapshots.back()->revision);
			result->setProperty("startSample", start);
			result->setProperty("frames", frames);
			result->setProperty("interleavedSamples", samples);
			writeEnvelope(eventSequence, correlation, "timeline_rendered", juce::var(result));
		}
		else if (kind == "transport" && payload != nullptr)
		{
			const auto action = payload->getProperty("action").toString();
			if (action == "play")
			{
				if (tone.position.load() >= tone.duration.load())
					tone.position.store(tone.loopEnabled.load() ? tone.loopStart.load() : 0);
				tone.playing.store(true);
			}
			else if (action == "query") {}
			else if (action == "pause") tone.playing.store(false);
			else if (action == "stop") { tone.playing.store(false); tone.position.store(0); }
			else if (action == "seek")
			{
				const auto sequence = static_cast<juce::int64>(payload->getProperty("seekSequence"));
				if (!payload->hasProperty("positionSamples") || sequence <= tone.seekSequence.load())
				{
					writeEnvelope(eventSequence, correlation, "error",
						makeError("JUCE_STALE_SEEK", "Seek requires a position and increasing sequence."));
					continue;
				}
				tone.position.store(juce::jlimit<juce::int64>(0, tone.duration.load(),
					static_cast<juce::int64>(payload->getProperty("positionSamples"))));
				tone.seekSequence.store(sequence);
			}
			else if (action == "loop")
			{
				const auto enabled = static_cast<bool>(payload->getProperty("loopEnabled"));
				const auto start = static_cast<juce::int64>(payload->getProperty("loopStartSample"));
				const auto end = static_cast<juce::int64>(payload->getProperty("loopEndSample"));
				if (enabled && (start < 0 || end <= start || end > tone.duration.load()))
				{
					writeEnvelope(eventSequence, correlation, "error",
						makeError("JUCE_INVALID_LOOP", "Loop boundaries are invalid."));
					continue;
				}
				tone.loopStart.store(start);
				tone.loopEnd.store(end);
				tone.loopEnabled.store(enabled);
			}
			else
			{
				writeEnvelope(eventSequence, correlation, "error",
					makeError("JUCE_UNSUPPORTED_COMMAND", "Transport action is unsupported."));
				continue;
			}
			writeEnvelope(eventSequence, correlation, "transport_position", makePosition(tone));
		}
		else
		{
			writeEnvelope(eventSequence, correlation, "error",
				makeError("JUCE_UNSUPPORTED_COMMAND", "Command kind is unsupported."));
		}
	}

	deviceManager.removeAudioCallback(&tone);
	deviceManager.closeAudioDevice();
	return 0;
}
