-- Current state of hubspot.deal_stage_history, from the bronze changelog.
{{ platform.bronze_current('hubspot', 'deal_stage_history', ['deal_id', 'stage', 'changed_at']) }}
