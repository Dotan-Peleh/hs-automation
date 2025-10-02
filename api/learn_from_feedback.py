"""
Analyze user feedback and generate improved detection rules.
Run this periodically to improve the model based on corrections.
"""
import json
from models import get_session, TicketFeedback, HsConversation

def analyze_feedback():
    """Analyze all feedback and suggest rule improvements."""
    with get_session() as s:
        corrections = s.query(TicketFeedback).filter_by(action_type='tag_correction').all()
    
    print(f"\n{'='*60}")
    print(f"📊 FEEDBACK ANALYSIS - {len(corrections)} corrections collected")
    print(f"{'='*60}\n")
    
    if not corrections:
        print("❌ No feedback collected yet. Start correcting tags in the dashboard!\n")
        return
    
    # Analyze patterns
    patterns = {}
    
    for fb in corrections:
        try:
            data = json.loads(fb.feedback_data or '{}')
            with get_session() as s2:
                conv = s2.query(HsConversation).filter_by(id=fb.conversation_id).first()
                if not conv:
                    continue
                
                text = ((conv.subject or '') + '\n' + (conv.last_text or '')).lower()
                correct_intent = data.get('correct_intent')
                correct_severity = data.get('correct_severity')
                notes = data.get('notes', '')
                
                if correct_intent:
                    if correct_intent not in patterns:
                        patterns[correct_intent] = {'examples': [], 'keywords': set()}
                    
                    patterns[correct_intent]['examples'].append({
                        'ticket': conv.number,
                        'subject': conv.subject,
                        'text_snippet': text[:150],
                        'severity': correct_severity,
                        'notes': notes
                    })
                    
                    # Extract potential keywords from the text
                    words = text.split()
                    for i, word in enumerate(words):
                        # Look for distinctive phrases (2-3 words)
                        if i < len(words) - 1:
                            phrase = f"{word} {words[i+1]}"
                            if len(phrase) > 10 and len(phrase) < 40:
                                patterns[correct_intent]['keywords'].add(phrase)
        except Exception as e:
            print(f"⚠️  Error processing feedback: {e}")
    
    # Generate suggested rules
    print("🧠 SUGGESTED RULE IMPROVEMENTS:\n")
    print("=" * 60)
    print("Add these to api/app.py in derive_custom_tags() function:\n")
    
    for intent, data in patterns.items():
        print(f"\n## {intent.upper()} ({len(data['examples'])} corrections)")
        print(f"# Suggested keywords based on your feedback:")
        
        # Show most common keywords
        common_keywords = list(data['keywords'])[:10]
        if common_keywords:
            print(f"if any(k in t for k in {tuple(common_keywords)}):") 
            print(f"    tags.append('intent:{intent}')")
            print(f"    return tags  # Early return\n")
        
        # Show examples
        print("# Examples you corrected:")
        for ex in data['examples'][:3]:
            print(f"#   Ticket #{ex['ticket']}: {ex['subject']}")
            if ex['notes']:
                print(f"#   Your note: {ex['notes']}")
        print()
    
    print("\n" + "=" * 60)
    print("💡 NEXT STEPS:")
    print("1. Review the suggested rules above")
    print("2. Copy relevant ones to api/app.py")
    print("3. Test with docker-compose restart")
    print("4. Keep correcting tags to refine further!")
    print("=" * 60 + "\n")

if __name__ == '__main__':
    analyze_feedback()

