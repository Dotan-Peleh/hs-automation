"""
Automatic learning system that applies user feedback to improve tagging.
Runs automatically during ticket analysis.
"""
import json
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

# Global cache to avoid repeated database queries
_feedback_cache = None
_cache_updated = None

def load_feedback_rules():
    """Load all user feedback corrections from database and build rules."""
    global _feedback_cache, _cache_updated
    
    # Cache for 5 minutes to avoid excessive DB queries
    if _feedback_cache and _cache_updated:
        if (datetime.utcnow() - _cache_updated).total_seconds() < 300:
            return _feedback_cache
    
    from models import get_session, TicketFeedback, HsConversation
    
    rules = {
        'intent_keywords': {},  # intent -> [keywords]
        'severity_overrides': {},  # text_pattern -> severity
        'exact_matches': {}  # subject -> (intent, severity)
    }
    
    with get_session() as s:
        corrections = s.query(TicketFeedback).filter_by(action_type='tag_correction').all()
        
        for fb in corrections:
            try:
                data = json.loads(fb.feedback_data or '{}')
                conv = s.query(HsConversation).filter_by(id=fb.conversation_id).first()
                if not conv:
                    continue
                
                correct_intent = data.get('correct_intent')
                correct_severity = data.get('correct_severity')
                
                # Extract key phrases from the corrected ticket
                text = ((conv.subject or '') + '\n' + (conv.last_text or '')).lower()
                subject = (conv.subject or '').lower()
                
                # Build rules based on patterns
                if correct_intent:
                    # Extract distinctive 2-3 word phrases
                    words = text.split()
                    for i in range(len(words) - 2):
                        phrase = ' '.join(words[i:i+3])
                        # Skip common words
                        if len(phrase) > 15 and len(phrase) < 50:
                            if phrase not in ['the game is', 'i have a', 'this is a']:
                                if correct_intent not in rules['intent_keywords']:
                                    rules['intent_keywords'][correct_intent] = set()
                                rules['intent_keywords'][correct_intent].add(phrase)
                    
                    # Also store exact subject matches
                    if subject:
                        rules['exact_matches'][subject] = (correct_intent, correct_severity)
                
                if correct_severity:
                    # Store severity overrides for specific patterns
                    if subject:
                        rules['severity_overrides'][subject] = correct_severity
                        
            except Exception:
                pass
    
    # Convert sets to lists for JSON serialization
    for intent in rules['intent_keywords']:
        rules['intent_keywords'][intent] = list(rules['intent_keywords'][intent])[:20]  # Keep top 20
    
    _feedback_cache = rules
    _cache_updated = datetime.utcnow()
    return rules

def apply_learned_corrections(text: str, subject: str, predicted_intent: Optional[str], predicted_severity: str) -> Tuple[Optional[str], str]:
    """
    Apply learned corrections from user feedback.
    Returns: (corrected_intent, corrected_severity)
    """
    rules = load_feedback_rules()
    
    text_lower = text.lower()
    subject_lower = subject.lower()
    
    # Check exact subject matches first (highest confidence)
    if subject_lower in rules['exact_matches']:
        learned_intent, learned_severity = rules['exact_matches'][subject_lower]
        return (learned_intent or predicted_intent, learned_severity or predicted_severity)
    
    # Check keyword patterns
    corrected_intent = predicted_intent
    for intent, keywords in rules['intent_keywords'].items():
        for keyword in keywords:
            if keyword in text_lower:
                # Found a match! Use the learned intent
                corrected_intent = intent
                break
        if corrected_intent != predicted_intent:
            break
    
    # Check severity overrides
    corrected_severity = predicted_severity
    for pattern, severity in rules['severity_overrides'].items():
        if pattern in text_lower or pattern in subject_lower:
            corrected_severity = severity
            break
    
    return (corrected_intent, corrected_severity)

def get_feedback_stats():
    """Get statistics about feedback and learning."""
    rules = load_feedback_rules()
    return {
        'total_learned_intents': len(rules['intent_keywords']),
        'total_exact_matches': len(rules['exact_matches']),
        'total_severity_rules': len(rules['severity_overrides']),
        'cache_age_seconds': (datetime.utcnow() - _cache_updated).total_seconds() if _cache_updated else None
    }

