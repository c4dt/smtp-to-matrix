# Changelog

## v0.0.6 (prerelease)

- config/server/scheduler: add configurable severity levels that prepend
  messages in the form of emojis according to regexes defined in config.yaml.

## v0.0.5 (prerelease)

- message: update chunk limit to 60000 and make it configurable via env variable

## v0.0.4 (prerelease)

- message: chunk messages larger than Matrix event size into multiple
  threaded events; preserve HTML formatted parts and provide small plaintext
  fallbacks for clients that don't support HTML.
- Tests updated to cover chunking behavior and combined plain+HTML size accounting.

## v0.0.3 (prerelease)

- scheduler: retry again in 1 minute after failed delivery

## v0.0.2 (prerelease)

- Automatically convert HTML emails to plaintext

## v0.0.1 (prerelease)

- Reformat the send-now summary line to `date - sender@host - subject`.
- Reformat the batch digest header to `date until otherdate - host - batch name - X messages`.

## v0.0.0 (prerelease)

- Initialize project
