"""
Rich test data generator - Creates realistic high school transcripts with detailed grades and courses.

This generator creates transcripts that:
- Include specific course names (AP Physics, Honors Chemistry, etc.)
- Include numerical grades with percentages
- Include high school years (9th, 10th, 11th, 12th grade)
- Include semester/quarter information
- Include detailed course difficulty levels
- Include teacher notes and academic standing
- Are properly formatted for Rapunzel to parse
"""

import random
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta


class RichTestDataGenerator:
    """Generates highly detailed, realistic high school transcripts for agent testing."""

    # Realistic AP and Honors courses organized by subject
    ADVANCED_COURSES = {
        'Mathematics': [
            'AP Calculus AB', 'AP Calculus BC', 'AP Statistics',
            'Honors Precalculus', 'Honors Algebra II'
        ],
        'Science': [
            'AP Biology', 'AP Chemistry', 'AP Physics 1', 'AP Physics 2', 'AP Physics C',
            'Honors Biology', 'Honors Chemistry', 'Honors Physics',
            'AP Environmental Science', 'AP Human Geography'
        ],
        'English': [
            'AP English Language', 'AP English Literature',
            'Honors English 9', 'Honors English 10', 'Honors English 11'
        ],
        'Social Studies': [
            'AP US History', 'AP World History', 'AP Government',
            'AP Psychology', 'AP Economics',
            'Honors US History', 'Honors World History'
        ],
        'Languages': [
            'AP Spanish Language', 'AP Spanish Literature',
            'Honors Spanish III', 'Honors French III'
        ],
        'Technology': [
            'AP Computer Science A', 'AP Computer Science Principles',
            'Honors Computer Science', 'Digital Design'
        ]
    }

    STANDARD_COURSES = {
        'Grade 9': [
            'English 9', 'Algebra I', 'Biology', 'World History',
            'Spanish I', 'Physical Education', 'Art I', 'General Science', 'Technology'
        ],
        'Grade 10': [
            'English 10', 'Geometry', 'Chemistry', 'US History I',
            'Spanish II', 'Health', 'Music Theory', 'Business Basics'
        ],
        'Grade 11': [
            'English 11', 'Algebra II', 'Physics', 'US History II',
            'Spanish III', 'Economics', 'Psychology', 'Art II'
        ],
        'Grade 12': [
            'English 12', 'Trigonometry', 'Marine Science', 'Government',
            'Spanish IV', 'Senior Seminar', 'Sociology', 'Business Ethics'
        ]
    }

    ELECTIVES = [
        'Debate', 'Robotics Club', 'Mock Trial', 'Forensics', 'Science Olympiad',
        'Yearbook', 'Student Newspaper', 'Theater', 'Orchestra', 'Jazz Band',
        'AP Research', 'Honors Seminar', 'Research Methods', 'Environmental Club'
    ]

    # Realistic grade distributions
    GRADE_TO_PERCENTAGE = {
        'A+': (97, 100),
        'A': (93, 96),
        'A-': (90, 92),
        'B+': (87, 89),
        'B': (83, 86),
        'B-': (80, 82),
        'C+': (77, 79),
        'C': (73, 76),
        'C-': (70, 72),
        'D+': (67, 69),
        'D': (63, 66),
        'D-': (60, 62),
        'F': (0, 59)
    }

    def __init__(self):
        """Initialize the rich test data generator."""
        self.current_year = 2026
        self.school_year_start = 2022

    def generate_rich_transcript(
        self,
        student_name: str,
        school_name: str,
        quality_tier: str = 'high',
        include_ap_courses: bool = True
    ) -> str:
        """
        Generate a highly detailed and realistic high school transcript.
        
        Args:
            student_name: Full name of the student
            school_name: Name of the high school
            quality_tier: 'high' (A/A- avg), 'medium' (B+/B avg), or 'low' (B/C avg)
            include_ap_courses: Whether to include AP courses
            
        Returns:
            Formatted transcript as string
        """
        grades_by_tier = {
            'high': ['A', 'A', 'A', 'A-', 'A-', 'A+', 'A'],
            'medium': ['B+', 'B', 'B', 'A-', 'B+', 'B', 'A-'],
            'low': ['B', 'B-', 'C+', 'B', 'C', 'B-', 'C+']
        }
        
        grade_pool = grades_by_tier.get(quality_tier, grades_by_tier['medium'])
        
        # Calculate GPA based on tier
        if quality_tier == 'high':
            weighted_gpa = round(random.uniform(3.7, 4.0), 2)
            unweighted_gpa = round(random.uniform(3.6, 3.95), 2)
        elif quality_tier == 'medium':
            weighted_gpa = round(random.uniform(3.2, 3.6), 2)
            unweighted_gpa = round(random.uniform(3.1, 3.55), 2)
        else:
            weighted_gpa = round(random.uniform(2.6, 3.2), 2)
            unweighted_gpa = round(random.uniform(2.5, 3.15), 2)
        
        class_rank = random.randint(1, 20) if quality_tier == 'high' else random.randint(21, 75)
        class_size = random.randint(380, 520)
        
        transcript = f"""
╔════════════════════════════════════════════════════════════════════════════╗
║                  OFFICIAL HIGH SCHOOL TRANSCRIPT                           ║
║                         State of Georgia                                   ║
╚════════════════════════════════════════════════════════════════════════════╝

STUDENT INFORMATION
═══════════════════════════════════════════════════════════════════════════════
Name:                          {student_name}
School:                        {school_name}
Graduation Date:               May 31, 2026
Student ID:                    {random.randint(100000, 999999)}
Grade Level (Current):         12

ACADEMIC STANDING
═══════════════════════════════════════════════════════════════════════════════
Cumulative GPA (Unweighted):   {unweighted_gpa}/4.0
Cumulative GPA (Weighted):     {weighted_gpa}/5.0
Class Rank:                    {class_rank} of {class_size}
Class Percentile:              {max(1, 100 - int((class_rank/class_size) * 100))}%
Academic Status:               EXCELLENT STANDING
Honor Roll:                    All Semesters (All A's and B's)
State Achievement:             Georgia Distinguished Scholar Program

"""
        
        # Add standardized test scores
        transcript += self._generate_standardized_tests(quality_tier)
        
        # Add course grades by year
        transcript += self._generate_grades_by_year(
            grade_pool, 
            quality_tier, 
            include_ap_courses
        )
        
        # Add AP exam results
        transcript += self._generate_ap_exam_results(quality_tier, include_ap_courses)
        
        # Add attendance and conduct
        transcript += self._generate_attendance_section()
        
        # Add transcript notes
        transcript += self._generate_transcript_notes(quality_tier)
        
        transcript += """
═══════════════════════════════════════════════════════════════════════════════
This is an official transcript of record. All records are maintained in the
Registrar's Office. This transcript is valid only when issued in a sealed envelope.

Issued: February 18, 2026
Registrar Signature: ________________________
"""
        
        return transcript

    def _generate_standardized_tests(self, quality_tier: str) -> str:
        """Generate realistic standardized test scores."""
        if quality_tier == 'high':
            sat = random.randint(1420, 1550)
            act = random.randint(32, 35)
            psat = random.randint(1400, 1500)
        elif quality_tier == 'medium':
            sat = random.randint(1150, 1350)
            act = random.randint(26, 30)
            psat = random.randint(1100, 1300)
        else:
            sat = random.randint(950, 1100)
            act = random.randint(21, 25)
            psat = random.randint(900, 1050)
        
        return f"""STANDARDIZED TEST SCORES
═══════════════════════════════════════════════════════════════════════════════
SAT (Taken {random.randint(1, 3)} times):
  Most Recent Score:         {sat}
    Evidence-Based Reading:  {sat // 2}
    Math:                    {sat - (sat // 2)}
  National Percentile:       {random.randint(80, 99) if quality_tier == 'high' else random.randint(50, 80)}%

ACT (Taken {random.randint(1, 2)} times):
  Composite Score:           {act}
    English:                 {random.randint(28, 36) if quality_tier == 'high' else random.randint(22, 30)}
    Math:                    {random.randint(28, 36) if quality_tier == 'high' else random.randint(22, 30)}
    Reading:                 {random.randint(28, 36) if quality_tier == 'high' else random.randint(22, 30)}
    Science:                 {random.randint(28, 36) if quality_tier == 'high' else random.randint(22, 30)}
  National Percentile:       {random.randint(80, 99) if quality_tier == 'high' else random.randint(50, 80)}%

PSAT Score:                  {psat}

"""

    def _generate_grades_by_year(
        self,
        grade_pool: List[str],
        quality_tier: str,
        include_ap: bool
    ) -> str:
        """Generate detailed grades organized by high school year."""
        transcript = "DETAILED COURSE GRADES\n"
        transcript += "═══════════════════════════════════════════════════════════════════════════════\n\n"
        
        for year in range(9, 13):
            year_name = {9: 'FRESHMAN', 10: 'SOPHOMORE', 11: 'JUNIOR', 12: 'SENIOR'}.get(year, 'UNKNOWN')
            school_year = f"{self.school_year_start + (year - 9)}-{self.school_year_start + (year - 8)}"
            
            transcript += f"{year_name} YEAR ({school_year})\n"
            transcript += "─" * 79 + "\n"
            
            # Select courses for this year
            if year == 9:
                courses = self.STANDARD_COURSES['Grade 9']
            elif year == 10:
                courses = self.STANDARD_COURSES['Grade 10']
            elif year == 11:
                courses = self.STANDARD_COURSES['Grade 11']
                if include_ap and quality_tier == 'high':
                    courses.extend(random.sample(self.ADVANCED_COURSES['Science'], k=1))
                    courses.extend(random.sample(self.ADVANCED_COURSES['Mathematics'], k=1))
            else:  # Senior year
                courses = self.STANDARD_COURSES['Grade 12']
                if include_ap:
                    num_ap = 2 if quality_tier == 'high' else 1 if quality_tier == 'medium' else 0
                    for _ in range(num_ap):
                        category = random.choice(list(self.ADVANCED_COURSES.keys()))
                        course = random.choice(self.ADVANCED_COURSES[category])
                        if course not in courses:
                            courses.append(course)
            
            # Add electives
            electives = random.sample(self.ELECTIVES, k=min(2, len(self.ELECTIVES)))
            courses.extend(electives)
            
            # Generate fall and spring semester
            for semester in ['Fall', 'Spring']:
                transcript += f"\n{semester} Semester:\n"
                semester_courses = random.sample(courses, k=min(5, len(courses)))
                
                for course in semester_courses:
                    grade = random.choice(grade_pool)
                    percentage_range = self.GRADE_TO_PERCENTAGE[grade]
                    percentage = random.randint(percentage_range[0], percentage_range[1])
                    credits = 1.0 if 'AP' not in course else 1.25
                    
                    # Format course line with detailed information
                    transcript += f"  {course:<40} {grade:>3}  ({percentage:>3}%) │ {credits} cr\n"
                
                transcript += "\n"
            
            transcript += "\n"
        
        return transcript

    def _generate_ap_exam_results(self, quality_tier: str, include_ap: bool) -> str:
        """Generate AP exam scores."""
        if not include_ap:
            return "AP EXAM RESULTS\n═══════════════════════════════════════════════════════════════════════════════\nNo AP Exams Taken\n\n"
        
        transcript = "AP EXAM RESULTS\n"
        transcript += "═══════════════════════════════════════════════════════════════════════════════\n"
        
        if quality_tier == 'high':
            score_pool = [5, 5, 5, 4, 4, 4]
            num_exams = random.randint(4, 6)
        elif quality_tier == 'medium':
            score_pool = [4, 4, 3, 3, 3, 2]
            num_exams = random.randint(2, 3)
        else:
            score_pool = [3, 3, 2, 2]
            num_exams = 1
        
        # Select AP courses taken
        ap_courses_taken = []
        for category in self.ADVANCED_COURSES:
            for course in self.ADVANCED_COURSES[category]:
                if 'AP' in course:
                    ap_courses_taken.append(course)
        
        taken = random.sample(ap_courses_taken, k=min(num_exams, len(ap_courses_taken)))
        
        transcript += "Exam Results:\n"
        transcript += f"{'Course':<35} {'Score':<10} {'Date Taken':<15}\n"
        transcript += "─" * 60 + "\n"
        
        for course in taken:
            score = random.choice(score_pool)
            date = f"May {random.randint(1, 20)}, {random.randint(2024, 2025)}"
            transcript += f"{course:<35} {score:<10} {date:<15}\n"
        
        transcript += f"\nAP Cumulative Score:  {len([s for s in score_pool if random.random() < 0.7])} out of {len(taken)} exams scored 3 or higher\n\n"
        
        return transcript

    def _generate_attendance_section(self) -> str:
        """Generate attendance and conduct information."""
        days_absent = random.randint(0, 8)
        days_tardy = random.randint(0, 6)
        
        return f"""ATTENDANCE AND CONDUCT
═══════════════════════════════════════════════════════════════════════════════
Days Absent (9-12):            {days_absent}
Days Tardy:                    {days_tardy}
Disciplinary Incidents:        {random.randint(0, 2)} Minor infractions
Citizenship Grade:             EXCELLENT (all semesters)

"""

    def _generate_transcript_notes(self, quality_tier: str) -> str:
        """Generate optional transcript notes and honors."""
        notes = "HONORS & AWARDS\n"
        notes += "═══════════════════════════════════════════════════════════════════════════════\n"
        
        if quality_tier == 'high':
            honors = [
                "Georgia Valedictorian Candidate",
                "National Merit Scholar",
                "National Honor Society (3 years)",
                "Georgia Governor's Honors Program Participant",
                "Science Olympiad State Champion",
                "STEM Leadership Award",
                "Outstanding Academic Achievement Award",
                "Principal's List (all semesters)"
            ]
        elif quality_tier == 'medium':
            honors = [
                "Honor Society Member (2 years)",
                "Principal's List (4 semesters)",
                "Department Achievement Award - Mathematics",
                "Perfect Attendance Award"
            ]
        else:
            honors = [
                "Principal's List (2 semesters)",
                "Perfect Attendance Award"
            ]
        
        selected = random.sample(honors, k=min(random.randint(2, 4), len(honors)))
        for honor in selected:
            notes += f"  • {honor}\n"
        
        notes += "\n"
        return notes


# Create a global instance for use throughout the application
rich_test_generator = RichTestDataGenerator()
