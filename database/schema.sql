-- Database schema for AI-powered application evaluation system

-- Table: Applications - Stores all uploaded applications
CREATE TABLE Applications (
    ApplicationID INT IDENTITY(1,1) PRIMARY KEY,
    ApplicantName NVARCHAR(255) NOT NULL,
    Email NVARCHAR(255),
    PhoneNumber NVARCHAR(50),
    Position NVARCHAR(255),
    UploadedDate DATETIME2 DEFAULT GETDATE(),
    ApplicationText NVARCHAR(MAX),  -- Extracted text from document
    OriginalFileName NVARCHAR(500),
    FileType NVARCHAR(50),
    BlobStoragePath NVARCHAR(1000),  -- Path if using Azure Blob Storage
    IsTrainingExample BIT DEFAULT 0,  -- True if this is an "excellent" example
    WasSelected BIT,  -- True if this was selected (for training examples)
    Status NVARCHAR(50) DEFAULT 'Pending',  -- Pending, Evaluated, Approved, Rejected
    CreatedBy NVARCHAR(255),
    UpdatedDate DATETIME2,
    Notes NVARCHAR(MAX)
);

-- Table: Grades - Stores academic or performance grades
CREATE TABLE Grades (
    GradeID INT IDENTITY(1,1) PRIMARY KEY,
    ApplicationID INT FOREIGN KEY REFERENCES Applications(ApplicationID),
    GradeType NVARCHAR(100),  -- e.g., 'GPA', 'Technical Test', 'Interview Score'
    GradeValue NVARCHAR(50),  -- e.g., '3.8', '85%', 'A'
    MaxValue NVARCHAR(50),  -- e.g., '4.0', '100%'
    Subject NVARCHAR(255),  -- Optional: specific course or skill
    Date DATETIME2,
    Notes NVARCHAR(MAX)
);

-- Table: AIEvaluations - Stores AI agent evaluations
CREATE TABLE AIEvaluations (
    EvaluationID INT IDENTITY(1,1) PRIMARY KEY,
    ApplicationID INT FOREIGN KEY REFERENCES Applications(ApplicationID),
    AgentName NVARCHAR(255),  -- Name of the AI agent that performed evaluation
    EvaluationDate DATETIME2 DEFAULT GETDATE(),
    OverallScore DECIMAL(5,2),  -- Overall score (0-100)
    TechnicalSkillsScore DECIMAL(5,2),
    CommunicationScore DECIMAL(5,2),
    ExperienceScore DECIMAL(5,2),
    CulturalFitScore DECIMAL(5,2),
    Strengths NVARCHAR(MAX),  -- AI-identified strengths
    Weaknesses NVARCHAR(MAX),  -- AI-identified weaknesses
    Recommendation NVARCHAR(50),  -- 'Strongly Recommend', 'Recommend', 'Consider', 'Reject'
    DetailedAnalysis NVARCHAR(MAX),  -- Full AI analysis
    ComparisonToExcellence NVARCHAR(MAX),  -- How it compares to training examples
    ModelUsed NVARCHAR(255),  -- GPT model version used
    ProcessingTimeMs INT
);

-- Table: SelectionDecisions - Final human decisions
CREATE TABLE SelectionDecisions (
    DecisionID INT IDENTITY(1,1) PRIMARY KEY,
    ApplicationID INT FOREIGN KEY REFERENCES Applications(ApplicationID),
    DecisionDate DATETIME2 DEFAULT GETDATE(),
    Decision NVARCHAR(50),  -- 'Selected', 'Rejected', 'Waitlist'
    DecisionBy NVARCHAR(255),  -- Who made the decision
    Justification NVARCHAR(MAX),
    AgreedWithAI BIT  -- Did the human agree with AI recommendation
);

-- Table: TrainingFeedback - Track how AI improves
CREATE TABLE TrainingFeedback (
    FeedbackID INT IDENTITY(1,1) PRIMARY KEY,
    ApplicationID INT FOREIGN KEY REFERENCES Applications(ApplicationID),
    EvaluationID INT FOREIGN KEY REFERENCES AIEvaluations(EvaluationID),
    FeedbackDate DATETIME2 DEFAULT GETDATE(),
    FeedbackType NVARCHAR(100),  -- 'Correction', 'Confirmation', 'Enhancement'
    HumanScore DECIMAL(5,2),  -- Human's score for comparison
    FeedbackNotes NVARCHAR(MAX),
    ProvidedBy NVARCHAR(255)
);

-- Indexes for better performance
CREATE INDEX IX_Applications_Status ON Applications(Status);
CREATE INDEX IX_Applications_IsTrainingExample ON Applications(IsTrainingExample);
CREATE INDEX IX_Applications_UploadedDate ON Applications(UploadedDate);
CREATE INDEX IX_AIEvaluations_ApplicationID ON AIEvaluations(ApplicationID);
CREATE INDEX IX_AIEvaluations_Recommendation ON AIEvaluations(Recommendation);
CREATE INDEX IX_SelectionDecisions_ApplicationID ON SelectionDecisions(ApplicationID);
