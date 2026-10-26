-- Current state of hubspot.pipeline_stage, from the bronze changelog.
{{ platform.bronze_current('hubspot', 'pipeline_stage', ['pipeline_id', 'stage_id']) }}
