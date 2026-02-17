"""Tests for custom instructions feature in LLM processing"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from slack_intel.pipeline.processors import OpenAIProcessor, PromptTemplates


class TestPromptTemplateStructure:
    """Test that prompt templates are correctly structured"""

    def test_foundation_templates_exist(self):
        """Verify all foundation templates are defined"""
        assert hasattr(PromptTemplates, 'FOUNDATION_MESSAGES')
        assert hasattr(PromptTemplates, 'FOUNDATION_USER_TIMELINE')
        assert hasattr(PromptTemplates, 'FOUNDATION_MULTI_CHANNEL')

    def test_instructions_templates_exist(self):
        """Verify all instruction templates are defined"""
        assert hasattr(PromptTemplates, 'INSTRUCTIONS_MESSAGES')
        assert hasattr(PromptTemplates, 'INSTRUCTIONS_USER_TIMELINE')
        assert hasattr(PromptTemplates, 'INSTRUCTIONS_MULTI_CHANNEL')

    def test_full_templates_preserve_backward_compatibility(self):
        """Verify full templates are concatenation of foundation + instructions"""
        # Single channel
        expected_messages = (
            PromptTemplates.FOUNDATION_MESSAGES +
            "\n\n" +
            PromptTemplates.INSTRUCTIONS_MESSAGES
        )
        assert PromptTemplates.SUMMARIZE_MESSAGES == expected_messages

        # User timeline
        expected_timeline = (
            PromptTemplates.FOUNDATION_USER_TIMELINE +
            "\n\n" +
            PromptTemplates.INSTRUCTIONS_USER_TIMELINE
        )
        assert PromptTemplates.SUMMARIZE_USER_TIMELINE == expected_timeline

        # Multi-channel
        expected_multi = (
            PromptTemplates.FOUNDATION_MULTI_CHANNEL +
            "\n\n" +
            PromptTemplates.INSTRUCTIONS_MULTI_CHANNEL
        )
        assert PromptTemplates.SUMMARIZE_MULTI_CHANNEL == expected_multi

    def test_foundation_contains_data_context(self):
        """Verify foundations contain required data context variables"""
        # All foundations should have message_content
        assert "{message_content}" in PromptTemplates.FOUNDATION_MESSAGES
        assert "{message_content}" in PromptTemplates.FOUNDATION_USER_TIMELINE
        assert "{message_content}" in PromptTemplates.FOUNDATION_MULTI_CHANNEL

        # Single channel foundation
        assert "{channel_name}" in PromptTemplates.FOUNDATION_MESSAGES
        assert "{date_range}" in PromptTemplates.FOUNDATION_MESSAGES
        assert "{org_context}" in PromptTemplates.FOUNDATION_MESSAGES

        # User timeline foundation
        assert "{channel_name}" in PromptTemplates.FOUNDATION_USER_TIMELINE
        assert "{date_range}" in PromptTemplates.FOUNDATION_USER_TIMELINE
        assert "{channels}" in PromptTemplates.FOUNDATION_USER_TIMELINE
        assert "{org_context}" in PromptTemplates.FOUNDATION_USER_TIMELINE

        # Multi-channel foundation
        assert "{channels}" in PromptTemplates.FOUNDATION_MULTI_CHANNEL
        assert "{date_range}" in PromptTemplates.FOUNDATION_MULTI_CHANNEL
        assert "{org_context}" in PromptTemplates.FOUNDATION_MULTI_CHANNEL

    def test_instructions_contain_analysis_framework(self):
        """Verify instructions contain analysis directives"""
        # Should have analysis sections/structure
        assert "KEY DISCUSSIONS" in PromptTemplates.INSTRUCTIONS_MESSAGES
        assert "FOCAL POINTS" in PromptTemplates.INSTRUCTIONS_USER_TIMELINE
        assert "Organizational Attention Flow" in PromptTemplates.INSTRUCTIONS_MULTI_CHANNEL

        # Should NOT contain data variables (those belong in foundation)
        assert "{message_content}" not in PromptTemplates.INSTRUCTIONS_MESSAGES
        assert "{message_content}" not in PromptTemplates.INSTRUCTIONS_USER_TIMELINE
        assert "{message_content}" not in PromptTemplates.INSTRUCTIONS_MULTI_CHANNEL


class TestCustomInstructionsFlow:
    """Test custom instructions parameter flow"""

    @patch('slack_intel.pipeline.processors.OpenAI')
    def test_custom_instructions_replaces_default_for_single_channel(self, mock_openai_client):
        """Test custom instructions replaces default for single_channel view"""
        # Setup
        processor = OpenAIProcessor(api_key="test-key")
        custom_prompt = "List the top 3 action items only."

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.output_text = "Action items: 1, 2, 3"
        mock_openai_client.return_value.responses.create.return_value = mock_response

        # Execute
        result_chunks = list(processor.generate_summary(
            message_content="Test message",
            channel_name="test-channel",
            date_range="2024-01-01",
            model="gpt-5",
            view_type="single_channel",
            custom_instructions=custom_prompt
        ))

        # Verify
        assert mock_openai_client.return_value.responses.create.called
        call_args = mock_openai_client.return_value.responses.create.call_args

        # Get the input prompt
        input_prompt = call_args.kwargs['input']

        # Should contain foundation elements
        assert "Test message" in input_prompt
        assert "test-channel" in input_prompt
        assert "2024-01-01" in input_prompt

        # Should contain custom instructions
        assert "List the top 3 action items only." in input_prompt

        # Should NOT contain default instructions
        assert "KEY DISCUSSIONS" not in input_prompt

    @patch('slack_intel.pipeline.processors.OpenAI')
    def test_default_instructions_used_when_no_custom(self, mock_openai_client):
        """Test default instructions are used when custom_instructions is None"""
        # Setup
        processor = OpenAIProcessor(api_key="test-key")

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.output_text = "Default analysis"
        mock_openai_client.return_value.responses.create.return_value = mock_response

        # Execute
        result_chunks = list(processor.generate_summary(
            message_content="Test message",
            channel_name="test-channel",
            date_range="2024-01-01",
            model="gpt-5",
            view_type="single_channel",
            custom_instructions=None  # Explicitly None
        ))

        # Verify
        call_args = mock_openai_client.return_value.responses.create.call_args
        input_prompt = call_args.kwargs['input']

        # Should contain default instructions
        assert "KEY DISCUSSIONS" in input_prompt

    @patch('slack_intel.pipeline.processors.OpenAI')
    def test_custom_instructions_with_user_timeline_view(self, mock_openai_client):
        """Test custom instructions works with user_timeline view type"""
        # Setup
        processor = OpenAIProcessor(api_key="test-key")
        custom_prompt = "Summarize this user's main contributions."

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.output_text = "User contributed to X, Y, Z"
        mock_openai_client.return_value.responses.create.return_value = mock_response

        # Execute
        result_chunks = list(processor.generate_summary(
            message_content="Test message",
            channel_name="user_john",
            date_range="2024-01-01",
            model="gpt-5",
            view_type="user_timeline",
            channels=["backend-devs", "frontend-team"],
            custom_instructions=custom_prompt
        ))

        # Verify
        call_args = mock_openai_client.return_value.responses.create.call_args
        input_prompt = call_args.kwargs['input']

        # Should use user timeline foundation
        assert "user_john" in input_prompt
        assert "backend-devs, frontend-team" in input_prompt

        # Should contain custom instructions
        assert "Summarize this user's main contributions." in input_prompt

        # Should NOT contain default user timeline instructions
        assert "FOCAL POINTS" not in input_prompt

    @patch('slack_intel.pipeline.processors.OpenAI')
    def test_custom_instructions_with_multi_channel_view(self, mock_openai_client):
        """Test custom instructions works with multi_channel view type"""
        # Setup
        processor = OpenAIProcessor(api_key="test-key")
        custom_prompt = "What are the common themes across channels?"

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.output_text = "Common themes: deployment, testing"
        mock_openai_client.return_value.responses.create.return_value = mock_response

        # Execute
        result_chunks = list(processor.generate_summary(
            message_content="Test message",
            channel_name="Multi-Channel",
            date_range="2024-01-01",
            model="gpt-5",
            view_type="multi_channel",
            channels=["backend-devs", "frontend-team", "ops"],
            custom_instructions=custom_prompt
        ))

        # Verify
        call_args = mock_openai_client.return_value.responses.create.call_args
        input_prompt = call_args.kwargs['input']

        # Should use multi-channel foundation
        assert "backend-devs, frontend-team, ops" in input_prompt

        # Should contain custom instructions
        assert "What are the common themes across channels?" in input_prompt

        # Should NOT contain default multi-channel instructions
        assert "ORGANIZATIONAL ATTENTION FLOW" not in input_prompt

    @patch('slack_intel.pipeline.processors.OpenAI')
    def test_org_context_preserved_with_custom_instructions(self, mock_openai_client):
        """Test organizational context is preserved when using custom instructions"""
        # Setup
        processor = OpenAIProcessor(api_key="test-key")
        custom_prompt = "Focus on leadership involvement."
        org_context = {
            "name": "Acme Corp",
            "stakeholders": [
                {"name": "Jane CEO", "role": "CEO", "weight": 10}
            ]
        }

        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.output_text = "Leadership analysis"
        mock_openai_client.return_value.responses.create.return_value = mock_response

        # Execute
        result_chunks = list(processor.generate_summary(
            message_content="Test message",
            channel_name="test-channel",
            date_range="2024-01-01",
            model="gpt-5",
            view_type="single_channel",
            org_context=org_context,
            custom_instructions=custom_prompt
        ))

        # Verify
        call_args = mock_openai_client.return_value.responses.create.call_args
        input_prompt = call_args.kwargs['input']

        # Should contain org context
        assert "Acme Corp" in input_prompt
        assert "Jane CEO" in input_prompt

        # Should contain custom instructions
        assert "Focus on leadership involvement." in input_prompt


class TestCustomInstructionsParameter:
    """Test that custom_instructions parameter exists in all required methods"""

    def test_generate_summary_accepts_custom_instructions(self):
        """Test OpenAIProcessor.generate_summary accepts custom_instructions"""
        from inspect import signature

        processor = OpenAIProcessor(api_key="test-key")
        sig = signature(processor.generate_summary)

        assert 'custom_instructions' in sig.parameters
        assert sig.parameters['custom_instructions'].default is None

    def test_chain_processor_accepts_custom_instructions(self):
        """Test ChainProcessor.analyze_messages accepts custom_instructions"""
        from inspect import signature
        from slack_intel.pipeline.chain import ChainProcessor

        processor = ChainProcessor(openai_api_key="test-key")
        sig = signature(processor.analyze_messages)

        assert 'custom_instructions' in sig.parameters
        assert sig.parameters['custom_instructions'].default is None
