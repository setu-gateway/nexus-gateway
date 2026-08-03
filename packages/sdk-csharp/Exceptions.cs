namespace SetuGateway;

/// <summary>Thrown when the gateway responds with a non-2xx status.</summary>
public class SetuApiException : Exception
{
    public int StatusCode { get; }
    public string Body { get; }

    public SetuApiException(int statusCode, string body)
        : base($"Setu Gateway request failed ({statusCode}): {body}")
    {
        StatusCode = statusCode;
        Body = body;
    }
}

/// <summary>Thrown when the gateway can't be reached at all.</summary>
public class SetuConnectionException : Exception
{
    public SetuConnectionException(string baseUrl, Exception innerException)
        : base($"Could not reach Setu Gateway at {baseUrl}", innerException)
    {
    }
}
