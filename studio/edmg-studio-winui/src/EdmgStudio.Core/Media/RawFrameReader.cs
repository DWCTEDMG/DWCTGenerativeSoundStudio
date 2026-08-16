namespace EdmgStudio.Core.Media;

public static class RawFrameReader
{
    public static async ValueTask<bool> ReadFrameAsync(
        Stream source,
        Memory<byte> destination,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (destination.IsEmpty)
        {
            throw new ArgumentException("A frame buffer cannot be empty.", nameof(destination));
        }

        int totalRead = 0;
        while (totalRead < destination.Length)
        {
            int read = await source.ReadAsync(destination[totalRead..], cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                if (totalRead == 0)
                {
                    return false;
                }

                throw new EndOfStreamException(
                    $"The decoder ended after {totalRead} of {destination.Length} frame bytes.");
            }

            totalRead += read;
        }

        return true;
    }
}
