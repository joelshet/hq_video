# Transcript

**[00:00:00]** Hey everyone. Today I'm going to show you how Acme Sync moves records between two apps in real time. So, um, let's start with the schema. Every table gets a field mapping, and the sync engine handles the upsert on both sides. Every table gets a field mapping, and the sync engine watches for changes on both sides. Once the webhook fires, the record lands in Postgres in about a second. That's the whole demo. Thanks for watching.
